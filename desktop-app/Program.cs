using System;
using System.IO;
using System.Windows.Forms;

namespace CourseInbox.Desktop
{
    public static class Program
    {
        [STAThread]
        public static int Main(string[] args)
        {
            int port;
            if (!TryReadPort(args, out port))
            {
                MessageBox.Show("启动参数无效。端口必须是 1 到 65535 的整数。", "CampusInbox 校园智能任务Agent", MessageBoxButtons.OK, MessageBoxIcon.Error);
                return 2;
            }
            using (SingleInstanceGuard instance = SingleInstanceGuard.TryAcquire("Local\\CourseInboxLearningAssistant"))
            {
                if (instance == null)
                {
                    MessageBox.Show("CampusInbox 校园智能任务Agent已经在运行，请查看任务栏或系统托盘。", "CampusInbox 校园智能任务Agent", MessageBoxButtons.OK, MessageBoxIcon.Information);
                    return 0;
                }
                Application.EnableVisualStyles();
                Application.SetCompatibleTextRenderingDefault(false);
                string root = FindProjectRoot(AppDomain.CurrentDomain.BaseDirectory);
                if (root == null)
                {
                    MessageBox.Show("未找到 CampusInbox 项目目录，请将软件保留在项目的 artifacts\\desktop 目录。", "CampusInbox 校园智能任务Agent", MessageBoxButtons.OK, MessageBoxIcon.Error);
                    return 1;
                }
                ServiceHost host = new ServiceHost(root, port);
                ServiceStartResult service;
                while (true)
                {
                    try { service = host.EnsureRunning(); break; }
                    catch (ServiceHostException error)
                    {
                        DialogResult result = MessageBox.Show(error.Message, "无法启动 CampusInbox", MessageBoxButtons.RetryCancel, MessageBoxIcon.Error);
                        if (result != DialogResult.Retry) return 1;
                    }
                }
                AppLifetime lifetime = new AppLifetime(host);
                DesktopApi api = new DesktopApi(service.BaseUri);
                ThreadPoolScheduler scheduler = new ThreadPoolScheduler();
                using (MainForm form = new MainForm(service.BaseUri, lifetime))
                using (AppController controller = new AppController(api, form, scheduler))
                using (DesktopAlertController alerts = new DesktopAlertController(api, form, scheduler, service.BaseUri))
                {
                    form.BindController(controller);
                    form.BindAlertsController(alerts);
                    Application.Run(form);
                }
                host.StopOwned();
                return 0;
            }
        }

        private static bool TryReadPort(string[] args, out int port)
        {
            port = 8765;
            for (int index = 0; index < args.Length; index++)
            {
                if (args[index] != "--port" || index + 1 >= args.Length || !int.TryParse(args[++index], out port) || port < 1 || port > 65535) return false;
            }
            return true;
        }

        private static string FindProjectRoot(string start)
        {
            DirectoryInfo directory = new DirectoryInfo(start);
            for (int depth = 0; directory != null && depth < 5; depth++, directory = directory.Parent)
                if (File.Exists(Path.Combine(directory.FullName, "server.py"))) return directory.FullName;
            return null;
        }
    }
}
