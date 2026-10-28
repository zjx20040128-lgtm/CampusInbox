using System;
using System.Threading;
using System.Threading.Tasks;

namespace CourseInbox.Desktop
{
    public sealed class ThreadPoolScheduler : IWorkScheduler
    {
        public void Run(Action action) { Task.Factory.StartNew(action); }
    }

    public sealed class AppController : IDisposable
    {
        private readonly IDesktopApi api;
        private readonly IAppView view;
        private readonly IWorkScheduler scheduler;
        private readonly object gate = new object();
        private bool running;
        private bool disposed;

        public AppController(IDesktopApi api, IAppView view, IWorkScheduler scheduler)
        {
            if (api == null) throw new ArgumentNullException("api");
            if (view == null) throw new ArgumentNullException("view");
            if (scheduler == null) throw new ArgumentNullException("scheduler");
            this.api = api;
            this.view = view;
            this.scheduler = scheduler;
        }

        public void Refresh() { Begin(delegate { return api.GetStatus(); }); }
        public void Login(bool visible) { Begin(delegate { return api.Login(visible); }); }
        public void Resume() { Begin(delegate { return api.Resume(); }); }
        public void Pause() { Begin(delegate { return api.Pause(); }); }
        public void Logout() { Begin(delegate { return api.Logout(); }); }

        private void Begin(Func<DesktopStatus> action)
        {
            lock (gate)
            {
                if (disposed || running) return;
                running = true;
            }
            scheduler.Run(delegate
            {
                bool qrRequested = false;
                try
                {
                    DesktopStatus status = action();
                    DesktopCounts counts = api.GetCounts();
                    DesktopViewState state = DesktopPresenter.From(status, counts);
                    qrRequested = state.ShowQr;
                    byte[] qr = qrRequested ? api.GetQrPng() : null;
                    view.Post(delegate { if (!disposed) view.Apply(state, qr); });
                }
                catch (Exception error)
                {
                    string message = string.IsNullOrWhiteSpace(error.Message) ? "连接暂时失败，请重试。" : error.Message;
                    view.Post(delegate
                    {
                        if (disposed) return;
                        if (qrRequested) view.ClearQr();
                        view.ShowTransientError(message);
                    });
                }
                finally
                {
                    lock (gate) running = false;
                }
            });
        }

        public void Dispose()
        {
            lock (gate) disposed = true;
        }
    }

    public sealed class AppLifetime
    {
        private readonly IServiceHost serviceHost;
        public AppLifetime(IServiceHost serviceHost)
        {
            if (serviceHost == null) throw new ArgumentNullException("serviceHost");
            this.serviceHost = serviceHost;
        }
        public bool ExitRequested { get; private set; }
        public bool RequestWindowClose() { return ExitRequested; }
        public bool RequestSystemClose() { ExitFromTray(); return true; }
        public void ExitFromTray()
        {
            if (ExitRequested) return;
            ExitRequested = true;
            serviceHost.StopOwned();
        }
    }

    public sealed class SingleInstanceGuard : IDisposable
    {
        private readonly Mutex mutex;
        private bool owns;
        private SingleInstanceGuard(Mutex mutex) { this.mutex = mutex; owns = true; }

        public static SingleInstanceGuard TryAcquire(string name)
        {
            bool created;
            Mutex mutex = new Mutex(true, name, out created);
            if (created) return new SingleInstanceGuard(mutex);
            mutex.Dispose();
            return null;
        }

        public void Dispose()
        {
            if (!owns) return;
            owns = false;
            try { mutex.ReleaseMutex(); }
            catch (ApplicationException) { }
            mutex.Dispose();
        }
    }
}
