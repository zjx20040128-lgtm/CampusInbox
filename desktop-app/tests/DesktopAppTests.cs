using System;
using System.Collections.Generic;
using System.Text;
using System.Windows.Forms;
using CourseInbox.Desktop;

public static class DesktopAppTests
{
    private static int failures;

    [STAThread]
    public static int Main()
    {
        Run("MapsIdleToLogin", MapsIdleToLogin);
        Run("MapsWaitingScanToQr", MapsWaitingScanToQr);
        Run("MapsSyncingToMonitoring", MapsSyncingToMonitoring);
        Run("MapsExpiredToRelogin", MapsExpiredToRelogin);
        Run("MapsUnknownToActionableError", MapsUnknownToActionableError);
        Run("PreservesIndependentSourceStates", PreservesIndependentSourceStates);
        Run("ParsesCountsWithoutMissingFieldFailures", ParsesCountsWithoutMissingFieldFailures);
        Run("AddsBootstrapTokenToProtectedRequests", AddsBootstrapTokenToProtectedRequests);
        Run("PostsJsonLoginOptions", PostsJsonLoginOptions);
        Run("AcceptsOnlyBoundedPngQr", AcceptsOnlyBoundedPngQr);
        Run("RejectsNonLoopbackEndpoint", RejectsNonLoopbackEndpoint);
        Run("ReusesHealthyCourseInbox", ReusesHealthyCourseInbox);
        Run("StartsServiceWhenPortIsFree", StartsServiceWhenPortIsFree);
        Run("DesktopLoadsModelEnvironment", DesktopLoadsModelEnvironment);
        Run("RejectsForeignServiceOnPort", RejectsForeignServiceOnPort);
        Run("DoesNotStopReusedService", DoesNotStopReusedService);
        Run("StopsOnlyOwnedProcessTree", StopsOnlyOwnedProcessTree);
        Run("ReportsMissingPython", ReportsMissingPython);
        Run("ReportsStartupTimeout", ReportsStartupTimeout);
        Run("RefreshDoesNotBlockViewThread", RefreshDoesNotBlockViewThread);
        Run("TransientRefreshErrorKeepsSessionState", TransientRefreshErrorKeepsSessionState);
        Run("LoginRequestsFreshQr", LoginRequestsFreshQr);
        Run("VisibleLoginUsesOfficialWindow", VisibleLoginUsesOfficialWindow);
        Run("PauseResumeLogoutCallExpectedEndpoint", PauseResumeLogoutCallExpectedEndpoint);
        Run("LogoutClearsQr", LogoutClearsQr);
        Run("UnknownStateShowsRetry", UnknownStateShowsRetry);
        Run("SecondInstanceIsRejected", SecondInstanceIsRejected);
        Run("WindowCloseMinimizesToTray", WindowCloseMinimizesToTray);
        Run("TrayExitStopsOwnedService", TrayExitStopsOwnedService);
        Run("TrayExitLeavesReusedServiceRunning", TrayExitLeavesReusedServiceRunning);
        Run("MainWindowExposesQrLoginWithoutPasswordField", MainWindowExposesQrLoginWithoutPasswordField);
        Run("InvalidQrClearsPreviousImage", InvalidQrClearsPreviousImage);
        Run("SystemShutdownDoesNotMinimizeToTray", SystemShutdownDoesNotMinimizeToTray);
        Run("ControllerRefreshStartsAfterWindowIsShown", ControllerRefreshStartsAfterWindowIsShown);
        DesktopAlertTests.RunAll(Run);
        Console.WriteLine(failures == 0 ? "Desktop app tests: PASS" : "Desktop app tests: FAIL " + failures);
        return failures == 0 ? 0 : 1;
    }

    private static void Run(string name, Action test)
    {
        try { test(); Console.WriteLine("PASS " + name); }
        catch (Exception error) { failures++; Console.WriteLine("FAIL " + name + ": " + error.Message); }
    }

    private static void DesktopLoadsModelEnvironment()
    {
        string root = System.IO.Path.Combine(System.IO.Path.GetTempPath(), "campusinbox-env-" + Guid.NewGuid().ToString("N"));
        System.IO.Directory.CreateDirectory(root);
        try
        {
            var info = new System.Diagnostics.ProcessStartInfo();
            info.UseShellExecute = false;
            WindowsServiceEnvironment.ApplyModelEnvironment(info, root);
            System.IO.File.WriteAllText(System.IO.Path.Combine(root, ".env"), "# model settings\nCI_MODEL_PROVIDER=ollama\n CI_MODEL = \"qwen3:4b-instruct\" \nCI_MODEL_BASE_URL=http://127.0.0.1:11434\nCI_MODEL_API_KEY='test-value'\nPATH=should-not-be-imported\n", Encoding.UTF8);
            string originalPath = info.EnvironmentVariables["PATH"];
            WindowsServiceEnvironment.ApplyModelEnvironment(info, root);
            Equal("ollama", info.EnvironmentVariables["CI_MODEL_PROVIDER"]);
            Equal("qwen3:4b-instruct", info.EnvironmentVariables["CI_MODEL"]);
            Equal("http://127.0.0.1:11434", info.EnvironmentVariables["CI_MODEL_BASE_URL"]);
            Equal("test-value", info.EnvironmentVariables["CI_MODEL_API_KEY"]);
            Equal(originalPath, info.EnvironmentVariables["PATH"]);
        }
        finally { System.IO.Directory.Delete(root, true); }
    }

    private static DesktopStatus Status(string state, bool enabled, bool sessionSaved)
    {
        DesktopStatus status = new DesktopStatus();
        status.State = state;
        status.Enabled = enabled;
        status.SessionSaved = sessionSaved;
        status.Sources = new Dictionary<string, DesktopSourceStatus>();
        return status;
    }

    private static void MapsIdleToLogin()
    {
        DesktopViewState view = DesktopPresenter.From(Status("idle", false, false), new DesktopCounts());
        Equal("尚未登录", view.Title);
        True(view.ShowLogin, "idle should show login");
        Equal("扫码登录学习通", view.LoginText);
        False(view.ShowQr, "idle should hide qr");
        False(view.ShowLogout, "idle should hide logout");
    }

    private static void MapsWaitingScanToQr()
    {
        DesktopStatus status = Status("waiting_scan", true, false);
        status.QrReady = true;
        DesktopViewState view = DesktopPresenter.From(status, new DesktopCounts());
        Equal("等待扫码", view.Title);
        True(view.ShowQr, "waiting_scan should show qr");
        True(view.ShowLogin, "waiting_scan should allow qr refresh");
        True(view.ShowVisibleLogin, "waiting_scan should allow official verification window");
        Equal("重新获取二维码", view.LoginText);
    }

    private static void MapsSyncingToMonitoring()
    {
        DesktopViewState view = DesktopPresenter.From(Status("syncing", true, true), new DesktopCounts());
        Equal("正在监测", view.Title);
        True(view.ShowPause, "syncing should offer pause");
        True(view.ShowLogout, "saved session should offer logout");
        False(view.ShowLogin, "syncing should not lead with login");
        False(view.ShowVisibleLogin, "syncing should hide official login window");
    }

    private static void MapsExpiredToRelogin()
    {
        DesktopViewState view = DesktopPresenter.From(Status("expired", true, true), new DesktopCounts());
        Equal("登录已失效", view.Title);
        True(view.ShowLogin, "expired should offer relogin");
        Equal("重新扫码", view.LoginText);
    }

    private static void MapsUnknownToActionableError()
    {
        DesktopViewState view = DesktopPresenter.From(Status("new-server-state", true, true), new DesktopCounts());
        Equal("连接需要处理", view.Title);
        Contains(view.Error, "未知状态");
        True(view.ShowResume, "unknown saved session should offer retry");
    }

    private static void PreservesIndependentSourceStates()
    {
        DesktopStatus status = Status("partial", true, true);
        status.Sources["chat"] = new DesktopSourceStatus { State = "retrying" };
        status.Sources["notice"] = new DesktopSourceStatus { State = "connected" };
        status.Sources["task_center"] = new DesktopSourceStatus { State = "partial", PendingCount = 3, Stage = "task_list", IssueSummary = "第5门课作业" };
        DesktopViewState view = DesktopPresenter.From(status, new DesktopCounts());
        Contains(view.SourcesText, "聊天：待重试 · 课程通知：已同步");
        Contains(view.SourcesText, "作业/考试：部分待重试（待检查/重试 3 · 第5门课作业 · 作业/考试列表待重试）");
    }

    private static void ParsesCountsWithoutMissingFieldFailures()
    {
        FakeTransport transport = ReadyTransport();
        transport.Add("GET", "/api/settings", 200, "application/json", "{\"chaoxing_web\":{\"received_count\":7,\"chat_count\":4}}");
        DesktopCounts counts = new DesktopApi(new Uri("http://127.0.0.1:8765/"), transport).GetCounts();
        Equal(7, counts.Received);
        Equal(4, counts.Chat);
        Equal(0, counts.CourseNotice);
        Equal(0, counts.TaskCenter);
    }

    private static void AddsBootstrapTokenToProtectedRequests()
    {
        FakeTransport transport = ReadyTransport();
        transport.Add("GET", "/api/chaoxing/desktop/status", 200, "application/json", FullStatusJson("idle"));
        DesktopStatus status = new DesktopApi(new Uri("http://127.0.0.1:8765/"), transport).GetStatus();
        Equal("idle", status.State);
        Equal(2, transport.Requests.Count);
        Equal("", transport.Requests[0].Authorization);
        Equal("Bearer 12345678901234567890123456789012", transport.Requests[1].Authorization);
    }

    private static void PostsJsonLoginOptions()
    {
        FakeTransport transport = ReadyTransport();
        transport.Add("POST", "/api/chaoxing/desktop/login", 200, "application/json", FullStatusJson("connecting"));
        new DesktopApi(new Uri("http://localhost:8765/"), transport).Login(true);
        FakeRequest request = transport.Requests[1];
        Equal("POST", request.Method);
        Equal("application/json", request.ContentType);
        Equal("{\"visible\":true}", Encoding.UTF8.GetString(request.Body));
    }

    private static void AcceptsOnlyBoundedPngQr()
    {
        byte[] png = new byte[] { 0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, 1 };
        FakeTransport valid = ReadyTransport();
        valid.Add("GET", "/api/chaoxing/desktop/qr", 200, "image/png", png);
        Equal(9, new DesktopApi(new Uri("http://127.0.0.1:8765/"), valid).GetQrPng().Length);

        FakeTransport invalid = ReadyTransport();
        invalid.Add("GET", "/api/chaoxing/desktop/qr", 200, "image/png", Encoding.UTF8.GetBytes("not png"));
        Throws<DesktopApiException>(delegate { new DesktopApi(new Uri("http://127.0.0.1:8765/"), invalid).GetQrPng(); });

        FakeTransport oversized = ReadyTransport();
        byte[] huge = new byte[2 * 1024 * 1024 + 1];
        huge[0] = 0x89; huge[1] = 0x50; huge[2] = 0x4e; huge[3] = 0x47;
        oversized.Add("GET", "/api/chaoxing/desktop/qr", 200, "image/png", huge);
        Throws<DesktopApiException>(delegate { new DesktopApi(new Uri("http://127.0.0.1:8765/"), oversized).GetQrPng(); });
    }

    private static void RejectsNonLoopbackEndpoint()
    {
        Throws<ArgumentException>(delegate { new DesktopApi(new Uri("http://192.168.1.8:8765/"), new FakeTransport()); });
    }

    private static void ReusesHealthyCourseInbox()
    {
        FakeServiceEnvironment environment = new FakeServiceEnvironment();
        environment.Probes.Enqueue(ServiceProbeKind.CourseInbox);
        ServiceStartResult result = new ServiceHost("C:\\CourseInbox", 8765, environment).EnsureRunning();
        False(result.Owned, "healthy existing service must be reused");
        Equal(0, environment.StartCount);
        Equal("http://127.0.0.1:8765/", result.BaseUri.AbsoluteUri);
    }

    private static void StartsServiceWhenPortIsFree()
    {
        FakeServiceEnvironment environment = new FakeServiceEnvironment();
        environment.Probes.Enqueue(ServiceProbeKind.Unavailable);
        environment.Probes.Enqueue(ServiceProbeKind.CourseInbox);
        ServiceStartResult result = new ServiceHost("C:\\CourseInbox", 8899, environment).EnsureRunning();
        True(result.Owned, "new service must be owned");
        Equal(1, environment.StartCount);
        Contains(environment.LastArguments, "--port 8899");
    }

    private static void RejectsForeignServiceOnPort()
    {
        FakeServiceEnvironment environment = new FakeServiceEnvironment();
        environment.Probes.Enqueue(ServiceProbeKind.Foreign);
        ServiceHostException error = ThrowsAndReturn<ServiceHostException>(delegate { new ServiceHost("C:\\CourseInbox", 8765, environment).EnsureRunning(); });
        Contains(error.Message, "端口 8765");
        Equal(0, environment.StartCount);
        False(environment.Process.Stopped, "foreign process must never be stopped");
    }

    private static void DoesNotStopReusedService()
    {
        FakeServiceEnvironment environment = new FakeServiceEnvironment();
        environment.Probes.Enqueue(ServiceProbeKind.CourseInbox);
        ServiceHost host = new ServiceHost("C:\\CourseInbox", 8765, environment);
        host.EnsureRunning();
        host.StopOwned();
        False(environment.Process.Stopped, "reused service must be left running");
    }

    private static void StopsOnlyOwnedProcessTree()
    {
        FakeServiceEnvironment environment = new FakeServiceEnvironment();
        environment.Probes.Enqueue(ServiceProbeKind.Unavailable);
        environment.Probes.Enqueue(ServiceProbeKind.CourseInbox);
        ServiceHost host = new ServiceHost("C:\\CourseInbox", 8765, environment);
        host.EnsureRunning();
        host.StopOwned();
        True(environment.Process.Stopped, "owned service must stop on explicit app exit");
    }

    private static void ReportsMissingPython()
    {
        FakeServiceEnvironment environment = new FakeServiceEnvironment();
        environment.Probes.Enqueue(ServiceProbeKind.Unavailable);
        environment.Python = null;
        ServiceHostException error = ThrowsAndReturn<ServiceHostException>(delegate { new ServiceHost("C:\\CourseInbox", 8765, environment).EnsureRunning(); });
        Contains(error.Message, "Python");
        Equal(0, environment.StartCount);
    }

    private static void ReportsStartupTimeout()
    {
        FakeServiceEnvironment environment = new FakeServiceEnvironment();
        environment.DefaultProbe = ServiceProbeKind.Unavailable;
        ServiceHostException error = ThrowsAndReturn<ServiceHostException>(delegate { new ServiceHost("C:\\CourseInbox", 8765, environment).EnsureRunning(); });
        Contains(error.Message, "启动超时");
        True(environment.Process.Stopped, "timed out owned process must be cleaned up");
    }

    private static void RefreshDoesNotBlockViewThread()
    {
        FakeDesktopApi api = new FakeDesktopApi();
        api.Status = Status("syncing", true, true);
        ManualScheduler scheduler = new ManualScheduler();
        FakeAppView view = new FakeAppView();
        AppController controller = new AppController(api, view, scheduler);
        controller.Refresh();
        Equal(0, view.ApplyCount);
        Equal(1, scheduler.Pending);
        scheduler.RunNext();
        Equal(1, view.ApplyCount);
        Equal("正在监测", view.LastState.Title);
    }

    private static void TransientRefreshErrorKeepsSessionState()
    {
        FakeDesktopApi api = new FakeDesktopApi();
        api.Status = Status("syncing", true, true);
        ManualScheduler scheduler = new ManualScheduler();
        FakeAppView view = new FakeAppView();
        AppController controller = new AppController(api, view, scheduler);
        controller.Refresh(); scheduler.RunNext();
        api.StatusError = new DesktopApiException("网络暂时不可用");
        controller.Refresh(); scheduler.RunNext();
        Equal("正在监测", view.LastState.Title);
        Contains(view.Error, "网络暂时不可用");
    }

    private static void LoginRequestsFreshQr()
    {
        FakeDesktopApi api = new FakeDesktopApi();
        api.LoginStatus = Status("waiting_scan", true, false);
        api.LoginStatus.QrReady = true;
        api.Qr = new byte[] { 1, 2, 3 };
        ManualScheduler scheduler = new ManualScheduler();
        FakeAppView view = new FakeAppView();
        AppController controller = new AppController(api, view, scheduler);
        controller.Login(false); scheduler.RunNext();
        False(api.LastLoginVisible, "normal login should stay hidden");
        Equal(1, api.QrReads);
        Equal(3, view.LastQr.Length);
        Equal("等待扫码", view.LastState.Title);
    }

    private static void VisibleLoginUsesOfficialWindow()
    {
        FakeDesktopApi api = new FakeDesktopApi();
        api.LoginStatus = Status("connecting", true, false);
        ManualScheduler scheduler = new ManualScheduler();
        AppController controller = new AppController(api, new FakeAppView(), scheduler);
        controller.Login(true); scheduler.RunNext();
        True(api.LastLoginVisible, "visible login must request official window");
    }

    private static void PauseResumeLogoutCallExpectedEndpoint()
    {
        FakeDesktopApi api = new FakeDesktopApi();
        api.PauseStatus = Status("paused", false, true);
        api.ResumeStatus = Status("syncing", true, true);
        api.LogoutStatus = Status("idle", false, false);
        ManualScheduler scheduler = new ManualScheduler();
        AppController controller = new AppController(api, new FakeAppView(), scheduler);
        controller.Pause(); scheduler.RunNext();
        controller.Resume(); scheduler.RunNext();
        controller.Logout(); scheduler.RunNext();
        Equal(1, api.PauseCalls);
        Equal(1, api.ResumeCalls);
        Equal(1, api.LogoutCalls);
    }

    private static void LogoutClearsQr()
    {
        FakeDesktopApi api = new FakeDesktopApi();
        api.LogoutStatus = Status("idle", false, false);
        ManualScheduler scheduler = new ManualScheduler();
        FakeAppView view = new FakeAppView();
        view.LastQr = new byte[] { 9 };
        AppController controller = new AppController(api, view, scheduler);
        controller.Logout(); scheduler.RunNext();
        True(view.LastQr == null, "logout must clear old qr");
        Equal("尚未登录", view.LastState.Title);
    }

    private static void UnknownStateShowsRetry()
    {
        FakeDesktopApi api = new FakeDesktopApi();
        api.Status = Status("future", true, true);
        ManualScheduler scheduler = new ManualScheduler();
        FakeAppView view = new FakeAppView();
        AppController controller = new AppController(api, view, scheduler);
        controller.Refresh(); scheduler.RunNext();
        Equal("连接需要处理", view.LastState.Title);
        True(view.LastState.ShowResume, "unknown session state should show retry");
    }

    private static void SecondInstanceIsRejected()
    {
        string name = "Local\\CourseInboxTest" + Guid.NewGuid().ToString("N");
        using (SingleInstanceGuard first = SingleInstanceGuard.TryAcquire(name))
        {
            True(first != null, "first instance should acquire mutex");
            using (SingleInstanceGuard second = SingleInstanceGuard.TryAcquire(name)) False(second != null, "second instance should be rejected");
        }
    }

    private static void WindowCloseMinimizesToTray()
    {
        FakeServiceHost host = new FakeServiceHost();
        AppLifetime lifetime = new AppLifetime(host);
        False(lifetime.RequestWindowClose(), "window close should not exit");
        Equal(0, host.StopCalls);
    }

    private static void TrayExitStopsOwnedService()
    {
        FakeServiceHost host = new FakeServiceHost();
        AppLifetime lifetime = new AppLifetime(host);
        lifetime.ExitFromTray();
        True(lifetime.ExitRequested, "tray exit should mark explicit exit");
        Equal(1, host.StopCalls);
    }

    private static void TrayExitLeavesReusedServiceRunning()
    {
        FakeServiceEnvironment environment = new FakeServiceEnvironment();
        environment.Probes.Enqueue(ServiceProbeKind.CourseInbox);
        ServiceHost host = new ServiceHost("C:\\CourseInbox", 8765, environment);
        host.EnsureRunning();
        new AppLifetime(host).ExitFromTray();
        False(environment.Process.Stopped, "tray exit must not kill reused service");
    }

    private static void MainWindowExposesQrLoginWithoutPasswordField()
    {
        using (MainForm form = new MainForm(new Uri("http://127.0.0.1:8765/"), new AppLifetime(new FakeServiceHost())))
        {
            Control login = FindControl(form, "loginButton");
            Control qr = FindControl(form, "qrPicture");
            True(login != null, "main window should expose login button");
            True(qr != null, "main window should expose qr picture");
            Equal("学习通官方登录二维码", qr.AccessibleName);
            False(ContainsPasswordInput(form), "main window must not contain a password input");
        }
    }

    private static void InvalidQrClearsPreviousImage()
    {
        FakeDesktopApi api = new FakeDesktopApi();
        api.Status = Status("waiting_scan", true, false);
        api.Status.QrReady = true;
        api.Qr = new byte[] { 1, 2, 3 };
        ManualScheduler scheduler = new ManualScheduler();
        FakeAppView view = new FakeAppView();
        AppController controller = new AppController(api, view, scheduler);
        controller.Refresh(); scheduler.RunNext();
        Equal(3, view.LastQr.Length);
        api.QrError = new DesktopApiException("登录二维码无效");
        controller.Refresh(); scheduler.RunNext();
        True(view.LastQr == null, "invalid replacement must clear the previous qr");
        Contains(view.Error, "二维码无效");
    }

    private static void SystemShutdownDoesNotMinimizeToTray()
    {
        FakeServiceHost host = new FakeServiceHost();
        AppLifetime lifetime = new AppLifetime(host);
        True(lifetime.RequestSystemClose(), "system close must be allowed");
        True(lifetime.ExitRequested, "system close should enter exit state");
        Equal(1, host.StopCalls);
    }

    private static void ControllerRefreshStartsAfterWindowIsShown()
    {
        FakeServiceHost host = new FakeServiceHost();
        ManualScheduler scheduler = new ManualScheduler();
        using (MainForm form = new MainForm(new Uri("http://127.0.0.1:8765/"), new AppLifetime(host)))
        using (AppController controller = new AppController(new FakeDesktopApi(), form, scheduler))
        {
            form.BindController(controller);
            Equal(0, scheduler.Pending);
            form.Show();
            Application.DoEvents();
            Equal(1, scheduler.Pending);
            form.Hide();
        }
    }

    private static Control FindControl(Control parent, string name)
    {
        if (parent.Name == name) return parent;
        foreach (Control child in parent.Controls)
        {
            Control match = FindControl(child, name);
            if (match != null) return match;
        }
        return null;
    }

    private static bool ContainsPasswordInput(Control parent)
    {
        TextBox text = parent as TextBox;
        if (text != null && (text.UseSystemPasswordChar || text.PasswordChar != '\0')) return true;
        foreach (Control child in parent.Controls) if (ContainsPasswordInput(child)) return true;
        return false;
    }

    private static FakeTransport ReadyTransport()
    {
        FakeTransport transport = new FakeTransport();
        transport.Add("GET", "/api/bootstrap", 200, "application/json", "{\"token\":\"12345678901234567890123456789012\"}");
        return transport;
    }

    private static string FullStatusJson(string state)
    {
        return "{\"enabled\":false,\"state\":\"" + state + "\",\"qr_ready\":false,\"last_success\":null,\"last_error\":\"\",\"queued\":0,\"session_saved\":false,\"sources\":{\"chat\":{\"state\":\"idle\"},\"notice\":{\"state\":\"idle\"}}}";
    }

    private static void True(bool value, string message) { if (!value) throw new Exception(message); }
    private static void False(bool value, string message) { if (value) throw new Exception(message); }
    private static void Equal(object expected, object actual) { if (!object.Equals(expected, actual)) throw new Exception("expected " + expected + ", got " + actual); }
    private static void Contains(string actual, string expected) { if (actual == null || actual.IndexOf(expected, StringComparison.Ordinal) < 0) throw new Exception("expected to contain " + expected + ", got " + actual); }
    private static void Throws<T>(Action action) where T : Exception
    {
        try { action(); }
        catch (T) { return; }
        catch (Exception error) { throw new Exception("expected " + typeof(T).Name + ", got " + error.GetType().Name); }
        throw new Exception("expected " + typeof(T).Name);
    }

    private static T ThrowsAndReturn<T>(Action action) where T : Exception
    {
        try { action(); }
        catch (T error) { return error; }
        catch (Exception error) { throw new Exception("expected " + typeof(T).Name + ", got " + error.GetType().Name); }
        throw new Exception("expected " + typeof(T).Name);
    }

    private sealed class FakeManagedProcess : IManagedProcess
    {
        public int Id { get { return 31415; } }
        public bool HasExited { get; set; }
        public bool Stopped { get; private set; }
        public void StopTree() { Stopped = true; HasExited = true; }
    }

    private sealed class FakeServiceHost : IServiceHost
    {
        public int StopCalls;
        public ServiceStartResult EnsureRunning() { return new ServiceStartResult(new Uri("http://127.0.0.1:8765/"), true); }
        public void StopOwned() { StopCalls++; }
    }

    private sealed class ManualScheduler : IWorkScheduler
    {
        private readonly Queue<Action> work = new Queue<Action>();
        public int Pending { get { return work.Count; } }
        public void Run(Action action) { work.Enqueue(action); }
        public void RunNext() { work.Dequeue()(); }
    }

    private sealed class FakeAppView : IAppView
    {
        public int ApplyCount;
        public DesktopViewState LastState;
        public byte[] LastQr;
        public string Error = "";
        public void Post(Action action) { action(); }
        public void Apply(DesktopViewState state, byte[] qrPng) { ApplyCount++; LastState = state; LastQr = qrPng; Error = state.Error ?? ""; }
        public void ShowTransientError(string message) { Error = message; }
        public void ClearQr() { LastQr = null; }
    }

    private sealed class FakeDesktopApi : IDesktopApi
    {
        public DesktopStatus Status = DesktopAppTests.Status("idle", false, false);
        public DesktopStatus LoginStatus = DesktopAppTests.Status("connecting", true, false);
        public DesktopStatus ResumeStatus = DesktopAppTests.Status("syncing", true, true);
        public DesktopStatus PauseStatus = DesktopAppTests.Status("paused", false, true);
        public DesktopStatus LogoutStatus = DesktopAppTests.Status("idle", false, false);
        public DesktopCounts Counts = new DesktopCounts();
        public byte[] Qr;
        public Exception QrError;
        public Exception StatusError;
        public bool LastLoginVisible;
        public int QrReads;
        public int ResumeCalls;
        public int PauseCalls;
        public int LogoutCalls;
        public DesktopStatus GetStatus() { if (StatusError != null) throw StatusError; return Status; }
        public DesktopCounts GetCounts() { return Counts; }
        public byte[] GetQrPng() { QrReads++; if (QrError != null) throw QrError; return Qr; }
        public DesktopStatus Login(bool visible) { LastLoginVisible = visible; return LoginStatus; }
        public DesktopStatus Resume() { ResumeCalls++; return ResumeStatus; }
        public DesktopStatus Pause() { PauseCalls++; return PauseStatus; }
        public DesktopStatus Logout() { LogoutCalls++; return LogoutStatus; }
    }

    private sealed class FakeServiceEnvironment : IServiceEnvironment
    {
        public readonly Queue<ServiceProbeKind> Probes = new Queue<ServiceProbeKind>();
        public readonly FakeManagedProcess Process = new FakeManagedProcess();
        public ServiceProbeKind DefaultProbe = ServiceProbeKind.Unavailable;
        public PythonCommand Python = new PythonCommand("python.exe", "");
        public int StartCount;
        public string LastArguments = "";

        public ServiceProbeKind Probe(Uri baseUri) { return Probes.Count > 0 ? Probes.Dequeue() : DefaultProbe; }
        public PythonCommand FindPython(string root) { return Python; }
        public IManagedProcess Start(PythonCommand command, string arguments, string workingDirectory) { StartCount++; LastArguments = arguments; return Process; }
        public void Wait(int milliseconds) { }
    }

    private sealed class FakeRequest
    {
        public string Method;
        public string Path;
        public byte[] Body;
        public string Authorization;
        public string ContentType;
    }

    private sealed class FakeTransport : IHttpTransport
    {
        private readonly Dictionary<string, Queue<HttpTransportResponse>> responses = new Dictionary<string, Queue<HttpTransportResponse>>();
        public readonly List<FakeRequest> Requests = new List<FakeRequest>();

        public void Add(string method, string path, int status, string contentType, string text)
        {
            Add(method, path, status, contentType, Encoding.UTF8.GetBytes(text));
        }

        public void Add(string method, string path, int status, string contentType, byte[] body)
        {
            string key = method + " " + path;
            if (!responses.ContainsKey(key)) responses[key] = new Queue<HttpTransportResponse>();
            responses[key].Enqueue(new HttpTransportResponse(status, contentType, body));
        }

        public HttpTransportResponse Send(Uri uri, string method, byte[] body, IDictionary<string, string> headers)
        {
            FakeRequest request = new FakeRequest();
            request.Method = method;
            request.Path = uri.AbsolutePath;
            request.Body = body ?? new byte[0];
            request.Authorization = headers.ContainsKey("Authorization") ? headers["Authorization"] : "";
            request.ContentType = headers.ContainsKey("Content-Type") ? headers["Content-Type"] : "";
            Requests.Add(request);
            string key = method + " " + uri.AbsolutePath;
            if (!responses.ContainsKey(key) || responses[key].Count == 0) throw new Exception("unexpected request " + key);
            return responses[key].Dequeue();
        }
    }
}
