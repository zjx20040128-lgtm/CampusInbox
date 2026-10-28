using System;
using System.Collections.Generic;

namespace CourseInbox.Desktop
{
    public sealed class DesktopSourceStatus
    {
        public string State { get; set; }
        public string LastChecked { get; set; }
        public string LastSuccess { get; set; }
        public string Error { get; set; }
        public string Stage { get; set; }
        public string IssueSummary { get; set; }
        public int CheckedCount { get; set; }
        public int CapturedCount { get; set; }
        public int FailedCount { get; set; }
        public int PendingCount { get; set; }
    }

    public sealed class DesktopStatus
    {
        public DesktopStatus() { Sources = new Dictionary<string, DesktopSourceStatus>(); }
        public bool Enabled { get; set; }
        public string State { get; set; }
        public bool QrReady { get; set; }
        public string LastChecked { get; set; }
        public string LastReceived { get; set; }
        public string LastSuccess { get; set; }
        public string LastError { get; set; }
        public int Queued { get; set; }
        public bool SessionSaved { get; set; }
        public IDictionary<string, DesktopSourceStatus> Sources { get; set; }
    }

    public sealed class DesktopCounts
    {
        public int Received { get; set; }
        public int Chat { get; set; }
        public int CourseNotice { get; set; }
        public int TaskCenter { get; set; }
    }

    public sealed class DesktopAlert
    {
        public string Id { get; set; }
        public string Kind { get; set; }
        public string Title { get; set; }
        public string Body { get; set; }
        public string Url { get; set; }
    }

    public sealed class DesktopAlertBatch
    {
        public DesktopAlertBatch() { Supported = true; Events = new List<DesktopAlert>(); }
        public bool Enabled { get; set; }
        public bool Supported { get; set; }
        public IList<DesktopAlert> Events { get; private set; }
    }

    public interface IDesktopAlertsApi
    {
        DesktopAlertBatch GetAlerts();
        void AcknowledgeAlerts(IList<string> ids);
        bool SetAlertsEnabled(bool enabled);
    }

    public interface IDesktopAlertView
    {
        void Post(Action action);
        void ApplyAlertSettings(bool enabled, string detail);
        bool TryShowAlert(DesktopAlert alert, Uri target);
    }

    public sealed class DesktopViewState
    {
        public string Title { get; set; }
        public string Summary { get; set; }
        public string Notice { get; set; }
        public string Detail { get; set; }
        public string Error { get; set; }
        public string SourcesText { get; set; }
        public string CountsText { get; set; }
        public string LoginText { get; set; }
        public bool ShowQr { get; set; }
        public bool ShowLogin { get; set; }
        public bool ShowPause { get; set; }
        public bool ShowResume { get; set; }
        public bool ShowLogout { get; set; }
        public bool ShowVisibleLogin { get; set; }
    }

    public sealed class HttpTransportResponse
    {
        public HttpTransportResponse(int statusCode, string contentType, byte[] body)
        {
            StatusCode = statusCode;
            ContentType = contentType ?? "";
            Body = body ?? new byte[0];
        }
        public int StatusCode { get; private set; }
        public string ContentType { get; private set; }
        public byte[] Body { get; private set; }
    }

    public interface IHttpTransport
    {
        HttpTransportResponse Send(Uri uri, string method, byte[] body, IDictionary<string, string> headers);
    }

    public interface IDesktopApi
    {
        DesktopStatus GetStatus();
        DesktopCounts GetCounts();
        byte[] GetQrPng();
        DesktopStatus Login(bool visible);
        DesktopStatus Resume();
        DesktopStatus Pause();
        DesktopStatus Logout();
    }

    public sealed class DesktopApiException : Exception
    {
        public DesktopApiException(string message) : base(message) { }
        public DesktopApiException(string message, Exception inner) : base(message, inner) { }
        public DesktopApiException(string message, int statusCode) : base(message) { StatusCode = statusCode; }
        public int StatusCode { get; private set; }
    }

    public enum ServiceProbeKind { Unavailable, CourseInbox, Foreign }

    public sealed class PythonCommand
    {
        public PythonCommand(string fileName, string prefixArguments)
        {
            FileName = fileName;
            PrefixArguments = prefixArguments ?? "";
        }
        public string FileName { get; private set; }
        public string PrefixArguments { get; private set; }
    }

    public interface IManagedProcess
    {
        int Id { get; }
        bool HasExited { get; }
        void StopTree();
    }

    public interface IServiceEnvironment
    {
        ServiceProbeKind Probe(Uri baseUri);
        PythonCommand FindPython(string root);
        IManagedProcess Start(PythonCommand command, string arguments, string workingDirectory);
        void Wait(int milliseconds);
    }

    public sealed class ServiceStartResult
    {
        public ServiceStartResult(Uri baseUri, bool owned) { BaseUri = baseUri; Owned = owned; }
        public Uri BaseUri { get; private set; }
        public bool Owned { get; private set; }
    }

    public interface IServiceHost
    {
        ServiceStartResult EnsureRunning();
        void StopOwned();
    }

    public sealed class ServiceHostException : Exception
    {
        public ServiceHostException(string message) : base(message) { }
        public ServiceHostException(string message, Exception inner) : base(message, inner) { }
    }

    public interface IWorkScheduler
    {
        void Run(Action action);
    }

    public interface IAppView
    {
        void Post(Action action);
        void Apply(DesktopViewState state, byte[] qrPng);
        void ShowTransientError(string message);
        void ClearQr();
    }
}
