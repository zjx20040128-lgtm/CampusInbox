using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Net;
using System.Text;
using System.Threading;
using System.Web.Script.Serialization;

namespace CourseInbox.Desktop
{
    public sealed class ServiceHost : IServiceHost
    {
        private readonly string root;
        private readonly int port;
        private readonly IServiceEnvironment environment;
        private readonly object gate = new object();
        private IManagedProcess ownedProcess;

        public ServiceHost(string root, int port) : this(root, port, new WindowsServiceEnvironment()) { }

        public ServiceHost(string root, int port, IServiceEnvironment environment)
        {
            if (string.IsNullOrEmpty(root)) throw new ArgumentException("项目目录无效。", "root");
            if (port < 1 || port > 65535) throw new ArgumentOutOfRangeException("port");
            if (environment == null) throw new ArgumentNullException("environment");
            this.root = root;
            this.port = port;
            this.environment = environment;
        }

        public ServiceStartResult EnsureRunning()
        {
            lock (gate)
            {
                Uri baseUri = new Uri("http://127.0.0.1:" + port + "/");
                ServiceProbeKind initial = environment.Probe(baseUri);
                if (initial == ServiceProbeKind.CourseInbox) return new ServiceStartResult(baseUri, false);
                if (initial == ServiceProbeKind.Foreign) throw PortConflict();

                PythonCommand python = environment.FindPython(root);
                if (python == null) throw new ServiceHostException("未找到 Python。请先安装 Python 3，或保留项目自带的 .venv。 ");
                string arguments = JoinArguments(python.PrefixArguments, Quote(Path.Combine(root, "server.py")), "--host", "127.0.0.1", "--port", port.ToString());
                try { ownedProcess = environment.Start(python, arguments, root); }
                catch (Exception error) { throw new ServiceHostException("CampusInbox 服务启动失败：" + error.Message, error); }

                for (int attempt = 0; attempt < 30; attempt++)
                {
                    environment.Wait(500);
                    ServiceProbeKind probe = environment.Probe(baseUri);
                    if (probe == ServiceProbeKind.CourseInbox) return new ServiceStartResult(baseUri, true);
                    if (probe == ServiceProbeKind.Foreign)
                    {
                        StopOwnedLocked();
                        throw PortConflict();
                    }
                    if (ownedProcess == null || ownedProcess.HasExited)
                    {
                        StopOwnedLocked();
                        throw new ServiceHostException("CampusInbox 服务启动后意外退出，请检查 Python 环境。");
                    }
                }
                StopOwnedLocked();
                throw new ServiceHostException("CampusInbox 服务启动超时，请检查端口和运行环境。");
            }
        }

        public void StopOwned()
        {
            lock (gate) StopOwnedLocked();
        }

        private void StopOwnedLocked()
        {
            IManagedProcess process = ownedProcess;
            ownedProcess = null;
            if (process != null && !process.HasExited) process.StopTree();
        }

        private ServiceHostException PortConflict()
        {
            return new ServiceHostException("端口 " + port + " 已被其他程序占用，请关闭冲突程序或更换端口。");
        }

        private static string Quote(string value) { return "\"" + value.Replace("\"", "\\\"") + "\""; }

        private static string JoinArguments(params string[] values)
        {
            List<string> result = new List<string>();
            foreach (string value in values) if (!string.IsNullOrWhiteSpace(value)) result.Add(value);
            return string.Join(" ", result.ToArray());
        }
    }

    public sealed class WindowsServiceEnvironment : IServiceEnvironment
    {
        public ServiceProbeKind Probe(Uri baseUri)
        {
            try
            {
                HttpWebRequest request = (HttpWebRequest)WebRequest.Create(new Uri(baseUri, "/api/health"));
                request.Method = "GET";
                request.Proxy = null;
                request.Timeout = 1500;
                request.ReadWriteTimeout = 1500;
                using (HttpWebResponse response = (HttpWebResponse)request.GetResponse())
                using (Stream stream = response.GetResponseStream())
                using (StreamReader reader = new StreamReader(stream, Encoding.UTF8))
                {
                    if ((int)response.StatusCode < 200 || (int)response.StatusCode >= 300) return ServiceProbeKind.Foreign;
                    object parsed = new JavaScriptSerializer().DeserializeObject(reader.ReadToEnd());
                    IDictionary<string, object> value = parsed as IDictionary<string, object>;
                    if (value == null) return ServiceProbeKind.Foreign;
                    object status, app;
                    return value.TryGetValue("status", out status) && value.TryGetValue("app", out app) && object.Equals(status, "ok") && object.Equals(app, "CourseInbox") ? ServiceProbeKind.CourseInbox : ServiceProbeKind.Foreign;
                }
            }
            catch (WebException error)
            {
                if (error.Response != null) { error.Response.Close(); return ServiceProbeKind.Foreign; }
                return ServiceProbeKind.Unavailable;
            }
            catch (IOException) { return ServiceProbeKind.Foreign; }
            catch (InvalidOperationException) { return ServiceProbeKind.Foreign; }
            catch (ArgumentException) { return ServiceProbeKind.Foreign; }
        }

        public PythonCommand FindPython(string root)
        {
            string local = Path.Combine(root, ".venv", "Scripts", "python.exe");
            if (File.Exists(local)) return new PythonCommand(local, "");
            string py = FindOnPath("py.exe");
            if (py != null) return new PythonCommand(py, "-3");
            string python = FindOnPath("python.exe");
            return python == null ? null : new PythonCommand(python, "");
        }

        public IManagedProcess Start(PythonCommand command, string arguments, string workingDirectory)
        {
            ProcessStartInfo info = new ProcessStartInfo();
            info.FileName = command.FileName;
            info.Arguments = arguments;
            info.WorkingDirectory = workingDirectory;
            info.UseShellExecute = false;
            info.CreateNoWindow = true;
            info.WindowStyle = ProcessWindowStyle.Hidden;
            ApplyModelEnvironment(info, workingDirectory);
            Process process = Process.Start(info);
            if (process == null) throw new InvalidOperationException("Python 进程未启动。");
            return new WindowsManagedProcess(process);
        }

        public static void ApplyModelEnvironment(ProcessStartInfo info, string root)
        {
            string path = Path.Combine(root, ".env");
            if (!File.Exists(path)) return;
            foreach (string line in File.ReadAllLines(path, Encoding.UTF8))
            {
                int separator = line.IndexOf('=');
                if (separator < 0) continue;
                string name = line.Substring(0, separator).Trim();
                if (name != "CI_MODEL_PROVIDER" && name != "CI_MODEL_BASE_URL" && name != "CI_MODEL" && name != "CI_MODEL_API_KEY") continue;
                string value = line.Substring(separator + 1).Trim();
                if (value.Length >= 2 && ((value[0] == '"' && value[value.Length - 1] == '"') || (value[0] == '\'' && value[value.Length - 1] == '\''))) value = value.Substring(1, value.Length - 2);
                info.EnvironmentVariables[name] = value;
            }
        }

        public void Wait(int milliseconds) { Thread.Sleep(milliseconds); }

        private static string FindOnPath(string name)
        {
            string path = Environment.GetEnvironmentVariable("PATH") ?? "";
            foreach (string entry in path.Split(Path.PathSeparator))
            {
                string directory = entry.Trim().Trim('"');
                if (directory.Length == 0) continue;
                try
                {
                    string candidate = Path.Combine(directory, name);
                    if (File.Exists(candidate)) return candidate;
                }
                catch (ArgumentException) { }
            }
            return null;
        }
    }

    public sealed class WindowsManagedProcess : IManagedProcess
    {
        private readonly Process process;
        public WindowsManagedProcess(Process process) { this.process = process; }
        public int Id { get { return process.Id; } }
        public bool HasExited { get { try { return process.HasExited; } catch (InvalidOperationException) { return true; } } }

        public void StopTree()
        {
            if (HasExited) return;
            try
            {
                ProcessStartInfo info = new ProcessStartInfo("taskkill.exe", "/PID " + process.Id + " /T /F");
                info.UseShellExecute = false;
                info.CreateNoWindow = true;
                using (Process killer = Process.Start(info)) if (killer != null) killer.WaitForExit(5000);
            }
            catch (Exception)
            {
                try { if (!process.HasExited) process.Kill(); }
                catch (Exception) { }
            }
        }
    }
}
