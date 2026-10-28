using System;
using System.Collections.Generic;
using System.Text.RegularExpressions;

namespace CourseInbox.Desktop
{
    public static class DesktopAlertLink
    {
        public static bool TryResolve(Uri baseUri, string value, out Uri target)
        {
            target = null;
            if (baseUri == null || baseUri.Scheme != Uri.UriSchemeHttp || !baseUri.IsLoopback || string.IsNullOrEmpty(value) || value.IndexOf('\\') >= 0) return false;
            Uri candidate;
            if (!Uri.TryCreate(baseUri, value, out candidate) || candidate.Scheme != baseUri.Scheme || !string.Equals(candidate.Host, baseUri.Host, StringComparison.OrdinalIgnoreCase) || candidate.Port != baseUri.Port || candidate.UserInfo.Length > 0 || candidate.AbsolutePath != "/") return false;
            string query = candidate.Query;
            bool message = Regex.IsMatch(query, "^\\?message=[0-9a-fA-F]{32}$") && candidate.Fragment == "#inbox";
            bool task = Regex.IsMatch(query, "^\\?task=[0-9a-fA-F]{32}$") && candidate.Fragment == "#tasks";
            if (!message && !task) return false;
            target = candidate;
            return true;
        }
    }

    public sealed class DesktopAlertController : IDisposable
    {
        private readonly IDesktopAlertsApi api;
        private readonly IDesktopAlertView view;
        private readonly IWorkScheduler scheduler;
        private readonly Uri baseUri;
        private readonly object gate = new object();
        private readonly HashSet<string> delivered = new HashSet<string>(StringComparer.Ordinal);
        private readonly HashSet<string> pendingAcks = new HashSet<string>(StringComparer.Ordinal);
        private bool running, disposed, enabled;
        private bool? requestedEnabled;

        public DesktopAlertController(IDesktopAlertsApi api, IDesktopAlertView view, IWorkScheduler scheduler, Uri baseUri)
        {
            if (api == null) throw new ArgumentNullException("api");
            if (view == null) throw new ArgumentNullException("view");
            if (scheduler == null) throw new ArgumentNullException("scheduler");
            if (baseUri == null) throw new ArgumentNullException("baseUri");
            this.api = api; this.view = view; this.scheduler = scheduler; this.baseUri = baseUri;
        }

        public void SetEnabled(bool value)
        {
            lock (gate) { if (disposed) return; requestedEnabled = value; }
            Poll();
        }

        public void Poll()
        {
            lock (gate) { if (disposed || running) return; running = true; }
            scheduler.Run(Read);
        }

        private void Read()
        {
            try
            {
                bool? setting;
                lock (gate) { if (disposed) { running = false; return; } setting = requestedEnabled; }
                if (setting.HasValue)
                {
                    bool saved = api.SetAlertsEnabled(setting.Value);
                    lock (gate) { enabled = saved; if (requestedEnabled == setting) requestedEnabled = null; }
                }
                try { FlushAcks(); } catch (Exception) { /* Keep delivery receipts for the next poll. */ }
                DesktopAlertBatch batch = api.GetAlerts();
                view.Post(delegate { Deliver(batch); });
            }
            catch (Exception error)
            {
                view.Post(delegate
                {
                    try { if (!disposed) view.ApplyAlertSettings(EffectiveEnabled(), "桌面提醒暂时不可用：" + error.Message); }
                    finally { Finish(); }
                });
            }
        }

        private bool EffectiveEnabled() { lock (gate) return requestedEnabled ?? enabled; }

        private void Deliver(DesktopAlertBatch batch)
        {
            bool ackScheduled = false;
            try
            {
                if (disposed) return;
                lock (gate) enabled = batch.Enabled;
                bool active = EffectiveEnabled();
                view.ApplyAlertSettings(active, batch.Supported ? "电脑和本软件保持运行时提醒；关闭网页仍可接收。" : "当前本机服务尚不支持桌面提醒，请更新服务。" );
                if (!active || !batch.Supported) return;
                foreach (DesktopAlert alert in batch.Events)
                {
                    if (alert == null || string.IsNullOrEmpty(alert.Id) || delivered.Contains(alert.Id)) continue;
                    Uri target;
                    if (!DesktopAlertLink.TryResolve(baseUri, alert.Url, out target)) continue;
                    if (view.TryShowAlert(alert, target)) { delivered.Add(alert.Id); pendingAcks.Add(alert.Id); }
                    break;
                }
                if (pendingAcks.Count > 0)
                {
                    ackScheduled = true;
                    scheduler.Run(delegate
                    {
                        try { FlushAcks(); }
                        catch (Exception) { /* A successful display must not repeat while its receipt is retried. */ }
                        finally { Finish(); }
                    });
                }
            }
            catch (Exception error)
            {
                if (!disposed) view.ApplyAlertSettings(EffectiveEnabled(), "桌面提醒暂时不可用：" + error.Message);
            }
            finally { if (!ackScheduled) Finish(); }
        }

        private void FlushAcks()
        {
            if (pendingAcks.Count == 0) return;
            List<string> ids = new List<string>(pendingAcks);
            api.AcknowledgeAlerts(ids);
            foreach (string id in ids) pendingAcks.Remove(id);
        }

        private void Finish() { lock (gate) running = false; }
        public void Dispose() { lock (gate) { disposed = true; running = false; } }
    }
}
