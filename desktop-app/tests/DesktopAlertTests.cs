using System;
using System.Collections.Generic;
using System.Text;
using System.Windows.Forms;
using CourseInbox.Desktop;

public static class DesktopAlertTests
{
    public static void RunAll(Action<string, Action> run)
    {
        run("AlertApiReadsAuthenticatedQueue", AlertApiReadsAuthenticatedQueue);
        run("AlertApiPostsAcknowledgmentsAndSettings", AlertApiPostsAcknowledgmentsAndSettings);
        run("OldServerAlert404KeepsSyncAvailable", OldServerAlert404KeepsSyncAvailable);
        run("AlertClickAcceptsOnlyLocalTaskTargets", AlertClickAcceptsOnlyLocalTaskTargets);
        run("AlertsShowOneThenAcknowledge", AlertsShowOneThenAcknowledge);
        run("FailedDisplayRemainsUnacknowledged", FailedDisplayRemainsUnacknowledged);
        run("ThrownDisplayRemainsUnacknowledged", ThrownDisplayRemainsUnacknowledged);
        run("FailedAckRetriesWithoutDuplicateDisplay", FailedAckRetriesWithoutDuplicateDisplay);
        run("DisabledAlertsDoNotDisplay", DisabledAlertsDoNotDisplay);
        run("AlertPollDoesNotOverlap", AlertPollDoesNotOverlap);
        run("AlertErrorsDoNotChangeSyncState", AlertErrorsDoNotChangeSyncState);
        run("DisableWhilePollIsInFlightStopsDelivery", DisableWhilePollIsInFlightStopsDelivery);
        run("DesktopReminderControlIsVisible", DesktopReminderControlIsVisible);
        run("DisposedAlertsDoNotDeliverQueuedResults", DisposedAlertsDoNotDeliverQueuedResults);
    }

    private static Uri BaseUri { get { return new Uri("http://127.0.0.1:8765/"); } }
    private const string MessageId = "0123456789abcdef0123456789abcdef";
    private static DesktopAlert Alert(string id)
    {
        return new DesktopAlert { Id = id, Kind = "new_pending", Title = "新待确认任务", Body = "请查看原始消息", Url = "/?message=" + MessageId + "#inbox" };
    }

    private static void AlertApiReadsAuthenticatedQueue()
    {
        Transport transport = new Transport();
        transport.Responses.Enqueue(Json(200, "{\"enabled\":true,\"events\":[{\"id\":\"event-1\",\"kind\":\"new_pending\",\"title\":\"新任务\",\"body\":\"请核对\",\"url\":\"/?message=" + MessageId + "#inbox\"}]}"));
        DesktopAlertBatch batch = new DesktopApi(BaseUri, transport).GetAlerts();
        True(batch.Enabled, "server setting should be read");
        Equal(1, batch.Events.Count);
        Equal("event-1", batch.Events[0].Id);
        Equal("新任务", batch.Events[0].Title);
        Equal("Bearer 12345678901234567890123456789012", transport.Authorization);
        Equal("GET /api/desktop/alerts", transport.LastRequest);
    }

    private static void AlertApiPostsAcknowledgmentsAndSettings()
    {
        Transport transport = new Transport();
        transport.Responses.Enqueue(Json(200, "{\"ok\":true}"));
        transport.Responses.Enqueue(Json(200, "{\"enabled\":false}"));
        DesktopApi api = new DesktopApi(BaseUri, transport);
        api.AcknowledgeAlerts(new string[] { "one", "two" });
        Equal("POST /api/desktop/alerts/ack", transport.LastRequest);
        Equal("{\"ids\":[\"one\",\"two\"]}", transport.LastBody);
        Equal("application/json", transport.ContentType);
        False(api.SetAlertsEnabled(false), "setting response must be returned");
        Equal("POST /api/desktop/alerts/settings", transport.LastRequest);
        Equal("{\"enabled\":false}", transport.LastBody);
    }

    private static void OldServerAlert404KeepsSyncAvailable()
    {
        Transport transport = new Transport();
        transport.Responses.Enqueue(Json(404, "{\"error\":\"not found\"}"));
        transport.Responses.Enqueue(Json(200, "{\"state\":\"syncing\",\"enabled\":true}"));
        DesktopApi api = new DesktopApi(BaseUri, transport);
        False(api.GetAlerts().Supported, "old API should report unsupported alerts");
        Equal("syncing", api.GetStatus().State);
    }

    private static void AlertClickAcceptsOnlyLocalTaskTargets()
    {
        Uri target;
        True(DesktopAlertLink.TryResolve(BaseUri, "/?message=" + MessageId + "#inbox", out target), "local message should open");
        Equal("http://127.0.0.1:8765/?message=" + MessageId + "#inbox", target.AbsoluteUri);
        True(DesktopAlertLink.TryResolve(BaseUri, "/?task=" + MessageId + "#tasks", out target), "local task should open");
        foreach (string url in new string[] { "https://evil.example/", "//evil.example/", "http://127.0.0.1:8766/?task=" + MessageId + "#tasks", "/api/bootstrap", "/api/desktop/alerts", "/?redirect=https://evil.example/", "javascript:alert(1)", "file:///C:/Windows/notepad.exe", "/\\evil.example/", "/?task=invalid#tasks", "/?task=" + MessageId + "#inbox", "http://user:pass@127.0.0.1:8765/?task=" + MessageId + "#tasks" })
            False(DesktopAlertLink.TryResolve(BaseUri, url, out target), "untrusted target must be rejected: " + url);
    }

    private static void AlertsShowOneThenAcknowledge()
    {
        Api api = new Api(); api.Batch.Events.Add(Alert("one")); api.Batch.Events.Add(Alert("two"));
        View view = new View(); Scheduler scheduler = new Scheduler();
        using (DesktopAlertController controller = new DesktopAlertController(api, view, scheduler, BaseUri))
        {
            controller.Poll(); Equal(0, view.Shown.Count); scheduler.Drain();
            Equal(1, view.Shown.Count); Equal("one", view.Shown[0]); Equal("one", string.Join(",", api.Acknowledged.ToArray()));
            controller.Poll(); scheduler.Drain();
            Equal("two", view.Shown[1]);
        }
    }

    private static void FailedDisplayRemainsUnacknowledged()
    {
        Api api = new Api(); api.Batch.Events.Add(Alert("one"));
        View view = new View(); view.CanShow = false; Scheduler scheduler = new Scheduler();
        using (DesktopAlertController controller = new DesktopAlertController(api, view, scheduler, BaseUri))
        {
            controller.Poll(); scheduler.Drain(); Equal(0, api.Acknowledged.Count);
            view.CanShow = true; controller.Poll(); scheduler.Drain(); Equal(1, view.Shown.Count); Equal(1, api.Acknowledged.Count);
        }
    }

    private static void FailedAckRetriesWithoutDuplicateDisplay()
    {
        Api api = new Api(); api.Batch.Events.Add(Alert("one")); api.FailAck = true;
        View view = new View(); Scheduler scheduler = new Scheduler();
        using (DesktopAlertController controller = new DesktopAlertController(api, view, scheduler, BaseUri))
        {
            controller.Poll(); scheduler.Drain(); Equal(1, view.Shown.Count); Equal(0, api.Acknowledged.Count);
            api.FailAck = false; controller.Poll(); scheduler.Drain(); Equal(1, view.Shown.Count); Equal(1, api.Acknowledged.Count);
        }
    }

    private static void ThrownDisplayRemainsUnacknowledged()
    {
        Api api = new Api(); api.Batch.Events.Add(Alert("one"));
        View view = new View(); view.ThrowOnShow = true; Scheduler scheduler = new Scheduler();
        using (DesktopAlertController controller = new DesktopAlertController(api, view, scheduler, BaseUri))
        {
            controller.Poll(); scheduler.Drain(); Equal(0, api.Acknowledged.Count);
            view.ThrowOnShow = false; controller.Poll(); scheduler.Drain(); Equal(1, view.Shown.Count); Equal(1, api.Acknowledged.Count);
        }
    }

    private static void DisabledAlertsDoNotDisplay()
    {
        Api api = new Api(); api.Batch.Enabled = false; api.Batch.Events.Add(Alert("one"));
        View view = new View(); Scheduler scheduler = new Scheduler();
        using (DesktopAlertController controller = new DesktopAlertController(api, view, scheduler, BaseUri))
        { controller.Poll(); scheduler.Drain(); Equal(0, view.Shown.Count); Equal(0, api.Acknowledged.Count); False(view.Enabled, "disabled setting must be visible"); }
    }

    private static void AlertPollDoesNotOverlap()
    {
        Api api = new Api(); View view = new View(); Scheduler scheduler = new Scheduler();
        using (DesktopAlertController controller = new DesktopAlertController(api, view, scheduler, BaseUri))
        {
            controller.Poll(); controller.Poll(); Equal(1, scheduler.Count); scheduler.Drain(); Equal(1, api.Reads);
            controller.Poll(); scheduler.Drain(); Equal(2, api.Reads);
        }
    }

    private static void AlertErrorsDoNotChangeSyncState()
    {
        Api api = new Api(); api.FailRead = true; View view = new View(); Scheduler scheduler = new Scheduler();
        using (DesktopAlertController controller = new DesktopAlertController(api, view, scheduler, BaseUri))
        {
            controller.Poll(); scheduler.Drain(); True(view.Detail.Length > 0, "alert failure should be actionable");
            Equal(0, view.Shown.Count); api.FailRead = false; api.FailSettings = true;
            controller.SetEnabled(false); scheduler.Drain(); True(view.Detail.Length > 0, "settings failure should be visible");
            api.FailSettings = false; controller.Poll(); scheduler.Drain(); False(api.Batch.Enabled, "failed setting should retry");
        }
        using (MainForm form = new MainForm(BaseUri, new AppLifetime(new Host())))
        using (DesktopAlertController controller = new DesktopAlertController(api, form, scheduler, BaseUri))
        {
            form.Apply(DesktopPresenter.From(new DesktopStatus { State = "syncing", Enabled = true, SessionSaved = true }, new DesktopCounts()), null);
            api.FailRead = true; controller.Poll(); scheduler.Drain();
            Equal("正在监测", form.Controls.Find("stateTitle", true)[0].Text);
            Equal("", form.Controls.Find("errorText", true)[0].Text);
            True(form.Controls.Find("desktopAlertsDetail", true)[0].Text.Contains("提醒连接失败"), "alert failure should appear beside its own setting");
        }
    }

    private static void DisableWhilePollIsInFlightStopsDelivery()
    {
        Api api = new Api(); api.Batch.Events.Add(Alert("one"));
        View view = new View(); view.QueuePosts = true; Scheduler scheduler = new Scheduler();
        using (DesktopAlertController controller = new DesktopAlertController(api, view, scheduler, BaseUri))
        {
            controller.Poll(); scheduler.Drain(); controller.SetEnabled(false); view.Drain(); scheduler.Drain();
            Equal(0, view.Shown.Count); Equal(0, api.Acknowledged.Count);
            controller.Poll(); scheduler.Drain(); view.Drain(); scheduler.Drain(); False(api.Batch.Enabled, "disable should persist");
        }
    }

    private static void DesktopReminderControlIsVisible()
    {
        using (MainForm form = new MainForm(BaseUri, new AppLifetime(new Host())))
        {
            Control[] controls = form.Controls.Find("desktopAlertsCheck", true);
            Equal(1, controls.Length); Equal("桌面提醒", controls[0].Text);
        }
    }

    private static void DisposedAlertsDoNotDeliverQueuedResults()
    {
        Api api = new Api(); api.Batch.Events.Add(Alert("one")); View view = new View(); view.QueuePosts = true;
        Scheduler scheduler = new Scheduler(); DesktopAlertController controller = new DesktopAlertController(api, view, scheduler, BaseUri);
        controller.Poll(); scheduler.Drain(); controller.Dispose(); view.Drain();
        Equal(0, view.Shown.Count); Equal(0, api.Acknowledged.Count);
        controller.Poll(); Equal(0, scheduler.Count);
    }

    private static HttpTransportResponse Json(int status, string body) { return new HttpTransportResponse(status, "application/json", Encoding.UTF8.GetBytes(body)); }
    private static void True(bool value, string message) { if (!value) throw new Exception(message); }
    private static void False(bool value, string message) { True(!value, message); }
    private static void Equal(object expected, object actual) { if (!object.Equals(expected, actual)) throw new Exception("expected " + expected + ", got " + actual); }

    private sealed class Transport : IHttpTransport
    {
        public Queue<HttpTransportResponse> Responses = new Queue<HttpTransportResponse>();
        public string LastRequest, LastBody, Authorization, ContentType;
        public HttpTransportResponse Send(Uri uri, string method, byte[] body, IDictionary<string, string> headers)
        {
            if (uri.AbsolutePath == "/api/bootstrap") return Json(200, "{\"token\":\"12345678901234567890123456789012\"}");
            LastRequest = method + " " + uri.AbsolutePath; LastBody = body == null ? "" : Encoding.UTF8.GetString(body);
            Authorization = headers["Authorization"]; ContentType = headers.ContainsKey("Content-Type") ? headers["Content-Type"] : "";
            return Responses.Dequeue();
        }
    }
    private sealed class Api : IDesktopAlertsApi
    {
        public DesktopAlertBatch Batch = new DesktopAlertBatch { Enabled = true };
        public List<string> Acknowledged = new List<string>();
        public bool FailAck, FailRead, FailSettings; public int Reads;
        public DesktopAlertBatch GetAlerts() { Reads++; if (FailRead) throw new Exception("提醒连接失败"); return Batch; }
        public void AcknowledgeAlerts(IList<string> ids) { if (FailAck) throw new Exception("ACK暂时失败"); Acknowledged.AddRange(ids); }
        public bool SetAlertsEnabled(bool enabled) { if (FailSettings) throw new Exception("设置保存失败"); Batch.Enabled = enabled; return enabled; }
    }
    private sealed class View : IDesktopAlertView
    {
        public List<string> Shown = new List<string>(); public bool CanShow = true, Enabled, QueuePosts, ThrowOnShow; public string Detail = "";
        private Queue<Action> posts = new Queue<Action>();
        public void Post(Action action) { if (QueuePosts) posts.Enqueue(action); else action(); }
        public void Drain() { while (posts.Count > 0) posts.Dequeue()(); }
        public void ApplyAlertSettings(bool enabled, string detail) { Enabled = enabled; Detail = detail; }
        public bool TryShowAlert(DesktopAlert alert, Uri target) { if (ThrowOnShow) throw new Exception("Windows通知不可用"); if (!CanShow) return false; Shown.Add(alert.Id); return true; }
    }
    private sealed class Scheduler : IWorkScheduler
    {
        private Queue<Action> work = new Queue<Action>(); public int Count { get { return work.Count; } }
        public void Run(Action action) { work.Enqueue(action); }
        public void Drain() { int count = 0; while (work.Count > 0) { if (++count > 20) throw new Exception("unbounded scheduling"); work.Dequeue()(); } }
    }
    private sealed class Host : IServiceHost
    {
        public ServiceStartResult EnsureRunning() { throw new NotSupportedException(); }
        public void StopOwned() { }
    }
}
