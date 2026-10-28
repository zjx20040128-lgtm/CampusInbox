using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using System.Net;
using System.Text;
using System.Web.Script.Serialization;

namespace CourseInbox.Desktop
{
    public sealed class DesktopApi : IDesktopApi, IDesktopAlertsApi
    {
        private const int MaxQrBytes = 2 * 1024 * 1024;
        private readonly Uri baseUri;
        private readonly IHttpTransport transport;
        private readonly JavaScriptSerializer json = new JavaScriptSerializer();
        private string token;

        public DesktopApi(Uri baseUri) : this(baseUri, new HttpWebRequestTransport()) { }

        public DesktopApi(Uri baseUri, IHttpTransport transport)
        {
            if (baseUri == null) throw new ArgumentNullException("baseUri");
            if (transport == null) throw new ArgumentNullException("transport");
            if (baseUri.Scheme != Uri.UriSchemeHttp || !baseUri.IsLoopback) throw new ArgumentException("桌面程序只连接本机 CampusInbox 服务。", "baseUri");
            this.baseUri = baseUri;
            this.transport = transport;
        }

        public DesktopStatus GetStatus() { return ParseStatus(Protected("GET", "/api/chaoxing/desktop/status", null)); }
        public DesktopCounts GetCounts()
        {
            IDictionary<string, object> root = ParseObject(Protected("GET", "/api/settings", null));
            IDictionary<string, object> value = ObjectValue(root, "chaoxing_web");
            DesktopCounts counts = new DesktopCounts();
            counts.Received = IntValue(value, "received_count");
            counts.Chat = IntValue(value, "chat_count");
            counts.CourseNotice = IntValue(value, "course_notice_count");
            counts.TaskCenter = IntValue(value, "task_center_count");
            return counts;
        }

        public byte[] GetQrPng()
        {
            HttpTransportResponse response = Protected("GET", "/api/chaoxing/desktop/qr", null);
            byte[] bytes = response.Body;
            if (bytes.Length > MaxQrBytes || bytes.Length < 8 || bytes[0] != 0x89 || bytes[1] != 0x50 || bytes[2] != 0x4e || bytes[3] != 0x47 || bytes[4] != 0x0d || bytes[5] != 0x0a || bytes[6] != 0x1a || bytes[7] != 0x0a)
                throw new DesktopApiException("登录二维码无效，请重新获取。");
            return bytes;
        }

        public DesktopStatus Login(bool visible) { return PostStatus("/api/chaoxing/desktop/login", "{\"visible\":" + (visible ? "true" : "false") + "}"); }
        public DesktopStatus Resume() { return PostStatus("/api/chaoxing/desktop/resume", "{}"); }
        public DesktopStatus Pause() { return PostStatus("/api/chaoxing/desktop/pause", "{}"); }
        public DesktopStatus Logout() { return PostStatus("/api/chaoxing/desktop/logout", "{}"); }

        public DesktopAlertBatch GetAlerts()
        {
            IDictionary<string, object> root;
            try { root = ParseObject(Protected("GET", "/api/desktop/alerts", null)); }
            catch (DesktopApiException error)
            {
                if (error.StatusCode == 404) return new DesktopAlertBatch { Supported = false };
                throw;
            }
            DesktopAlertBatch batch = new DesktopAlertBatch { Enabled = BoolValue(root, "enabled") };
            object value;
            IEnumerable events = root.TryGetValue("events", out value) ? value as IEnumerable : null;
            if (events == null) return batch;
            foreach (object item in events)
            {
                IDictionary<string, object> entry = item as IDictionary<string, object>;
                string id = StringValue(entry, "id");
                if (id.Length == 0 || id.Length > 512) continue;
                batch.Events.Add(new DesktopAlert { Id = id, Kind = StringValue(entry, "kind"), Title = StringValue(entry, "title"), Body = StringValue(entry, "body"), Url = StringValue(entry, "url") });
                if (batch.Events.Count >= 20) break;
            }
            return batch;
        }

        public void AcknowledgeAlerts(IList<string> ids)
        {
            string body;
            lock (json) body = json.Serialize(new Dictionary<string, object> { { "ids", ids } });
            Protected("POST", "/api/desktop/alerts/ack", Encoding.UTF8.GetBytes(body));
        }

        public bool SetAlertsEnabled(bool enabled)
        {
            string body = "{\"enabled\":" + (enabled ? "true" : "false") + "}";
            return BoolValue(ParseObject(Protected("POST", "/api/desktop/alerts/settings", Encoding.UTF8.GetBytes(body))), "enabled");
        }

        private DesktopStatus PostStatus(string path, string body)
        {
            return ParseStatus(Protected("POST", path, Encoding.UTF8.GetBytes(body)));
        }

        private HttpTransportResponse Protected(string method, string path, byte[] body)
        {
            EnsureToken();
            Dictionary<string, string> headers = new Dictionary<string, string>();
            headers["Authorization"] = "Bearer " + token;
            if (method == "POST") headers["Content-Type"] = "application/json";
            return Checked(transport.Send(new Uri(baseUri, path), method, body, headers));
        }

        private void EnsureToken()
        {
            if (!string.IsNullOrEmpty(token)) return;
            HttpTransportResponse response = Checked(transport.Send(new Uri(baseUri, "/api/bootstrap"), "GET", null, new Dictionary<string, string>()));
            string value = StringValue(ParseObject(response), "token");
            if (value.Length < 24) throw new DesktopApiException("本机访问令牌无效，请重新启动 CampusInbox 服务。");
            token = value;
        }

        private HttpTransportResponse Checked(HttpTransportResponse response)
        {
            if (response == null) throw new DesktopApiException("本机服务没有返回响应。");
            if (response.StatusCode >= 200 && response.StatusCode < 300) return response;
            string message = "本机服务请求失败（" + response.StatusCode + "）。";
            try
            {
                string error = StringValue(ParseObject(response), "error");
                if (error.Length > 0) message = error;
            }
            catch (DesktopApiException) { }
            throw new DesktopApiException(message, response.StatusCode);
        }

        private DesktopStatus ParseStatus(HttpTransportResponse response)
        {
            IDictionary<string, object> root = ParseObject(response);
            DesktopStatus status = new DesktopStatus();
            status.Enabled = BoolValue(root, "enabled");
            status.State = StringValue(root, "state");
            status.QrReady = BoolValue(root, "qr_ready");
            status.LastChecked = NullableStringValue(root, "last_checked");
            status.LastReceived = NullableStringValue(root, "last_received");
            status.LastSuccess = NullableStringValue(root, "last_success");
            status.LastError = StringValue(root, "last_error");
            status.Queued = IntValue(root, "queued");
            status.SessionSaved = BoolValue(root, "session_saved");
            IDictionary<string, object> sources = ObjectValue(root, "sources");
            foreach (string name in new string[] { "chat", "notice", "task_center" })
            {
                IDictionary<string, object> source = ObjectValue(sources, name);
                if (source.Count > 0) status.Sources[name] = new DesktopSourceStatus { State = StringValue(source, "state"), LastChecked = NullableStringValue(source, "last_checked"), LastSuccess = NullableStringValue(source, "last_success"), Error = StringValue(source, "error"), Stage = StringValue(source, "stage"), IssueSummary = StringValue(source, "issue_summary"), CheckedCount = IntValue(source, "checked_count"), CapturedCount = IntValue(source, "captured_count"), FailedCount = IntValue(source, "failed_count"), PendingCount = IntValue(source, "pending_count") };
            }
            return status;
        }

        private IDictionary<string, object> ParseObject(HttpTransportResponse response)
        {
            try
            {
                object value;
                lock (json) value = json.DeserializeObject(Encoding.UTF8.GetString(response.Body));
                IDictionary<string, object> result = value as IDictionary<string, object>;
                if (result == null) throw new InvalidOperationException();
                return result;
            }
            catch (Exception error)
            {
                throw new DesktopApiException("本机服务返回了无法读取的数据。", error);
            }
        }

        private static IDictionary<string, object> ObjectValue(IDictionary<string, object> source, string name)
        {
            object value;
            IDictionary<string, object> result;
            return source != null && source.TryGetValue(name, out value) && (result = value as IDictionary<string, object>) != null ? result : new Dictionary<string, object>();
        }

        private static string StringValue(IDictionary<string, object> source, string name)
        {
            object value;
            return source != null && source.TryGetValue(name, out value) && value is string ? (string)value : "";
        }

        private static string NullableStringValue(IDictionary<string, object> source, string name) { return StringValue(source, name); }
        private static bool BoolValue(IDictionary<string, object> source, string name)
        {
            object value;
            return source != null && source.TryGetValue(name, out value) && value is bool && (bool)value;
        }

        private static int IntValue(IDictionary<string, object> source, string name)
        {
            object value;
            if (source == null || !source.TryGetValue(name, out value) || value == null) return 0;
            try { return Convert.ToInt32(value); }
            catch (Exception) { return 0; }
        }
    }

    public sealed class HttpWebRequestTransport : IHttpTransport
    {
        private const int MaxResponseBytes = 4 * 1024 * 1024;

        public HttpTransportResponse Send(Uri uri, string method, byte[] body, IDictionary<string, string> headers)
        {
            try
            {
                HttpWebRequest request = (HttpWebRequest)WebRequest.Create(uri);
                request.Method = method;
                request.Timeout = 10000;
                request.ReadWriteTimeout = 10000;
                request.Proxy = null;
                string value;
                if (headers != null && headers.TryGetValue("Authorization", out value)) request.Headers[HttpRequestHeader.Authorization] = value;
                if (headers != null && headers.TryGetValue("Content-Type", out value)) request.ContentType = value;
                if (body != null && body.Length > 0)
                {
                    request.ContentLength = body.Length;
                    using (Stream stream = request.GetRequestStream()) stream.Write(body, 0, body.Length);
                }
                else if (method == "POST") request.ContentLength = 0;
                using (HttpWebResponse response = (HttpWebResponse)request.GetResponse()) return Read(response);
            }
            catch (WebException error)
            {
                HttpWebResponse response = error.Response as HttpWebResponse;
                if (response != null) using (response) return Read(response);
                throw new DesktopApiException("无法连接本机 CampusInbox 服务。", error);
            }
        }

        private static HttpTransportResponse Read(HttpWebResponse response)
        {
            using (Stream input = response.GetResponseStream())
            using (MemoryStream output = new MemoryStream())
            {
                byte[] buffer = new byte[8192];
                int count;
                while ((count = input.Read(buffer, 0, buffer.Length)) > 0)
                {
                    if (output.Length + count > MaxResponseBytes) throw new DesktopApiException("本机服务响应过大。");
                    output.Write(buffer, 0, count);
                }
                return new HttpTransportResponse((int)response.StatusCode, response.ContentType, output.ToArray());
            }
        }
    }
}
