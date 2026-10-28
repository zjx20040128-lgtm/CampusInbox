using System;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Windows.Forms;
using Microsoft.Win32;

namespace CourseInbox.Desktop
{
    public sealed class MainForm : Form, IAppView, IDesktopAlertView
    {
        private readonly Uri baseUri;
        private readonly AppLifetime lifetime;
        private readonly NotifyIcon tray;
        private readonly Timer timer;
        private readonly Timer alertTimer;
        private readonly CheckBox desktopAlertsCheck;
        private readonly Label desktopAlertsDetail;
        private readonly ToolStripMenuItem alertsMenuItem;
        private readonly Label stateTitle;
        private readonly Label stateDetail;
        private readonly Label sourcesText;
        private readonly Label countsText;
        private readonly Label errorText;
        private readonly Label timelineText;
        private readonly Label errorDetail;
        private readonly TableLayoutPanel detailsPanel;
        private readonly TableLayoutPanel cardLayout;
        private readonly LinkLabel detailsToggle;
        private readonly PictureBox qrPicture;
        private readonly Panel qrPanel;
        private readonly Button loginButton;
        private readonly Button visibleLoginButton;
        private readonly Button resumeButton;
        private readonly Button pauseButton;
        private readonly Button logoutButton;
        private AppController controller;
        private DesktopAlertController alertsController;
        private bool applyingAlertSettings;
        private Uri activeAlertTarget;
        private DateTime nextAlertAt = DateTime.MinValue;
        private bool trayTipShown;
        private bool controllerStarted;

        public MainForm(Uri baseUri, AppLifetime lifetime)
        {
            if (baseUri == null) throw new ArgumentNullException("baseUri");
            if (lifetime == null) throw new ArgumentNullException("lifetime");
            this.baseUri = baseUri;
            this.lifetime = lifetime;
            Text = "CampusInbox 校园智能任务Agent";
            Name = "mainWindow";
            AccessibleName = "CampusInbox 校园智能任务Agent";
            StartPosition = FormStartPosition.CenterScreen;
            MinimumSize = new Size(760, 660);
            Size = new Size(880, 760);
            BackColor = Color.FromArgb(247, 249, 246);
            Font = new Font("Microsoft YaHei UI", 10F, FontStyle.Regular, GraphicsUnit.Point);
            AutoScaleMode = AutoScaleMode.Dpi;

            Panel page = new Panel { Dock = DockStyle.Fill, Padding = new Padding(32), AutoScroll = true };
            Controls.Add(page);
            TableLayoutPanel layout = new TableLayoutPanel { Dock = DockStyle.Top, AutoSize = true, ColumnCount = 1, RowCount = 8 };
            layout.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
            page.Controls.Add(layout);

            Label eyebrow = new Label { AutoSize = true, Text = "COURSEINBOX · 学习通账号", ForeColor = Color.FromArgb(105, 129, 112), Font = new Font(Font, FontStyle.Bold), Margin = new Padding(0, 0, 0, 8) };
            Label heading = new Label { AutoSize = true, Text = "扫码登录并持续监测消息", ForeColor = Color.FromArgb(22, 53, 45), Font = new Font(Font.FontFamily, 22F, FontStyle.Bold), Margin = new Padding(0, 0, 0, 8) };
            Label intro = new Label { AutoSize = true, MaximumSize = new Size(760, 0), Text = "二维码来自学习通官方登录页面。软件不会要求或保存你的学习通密码。", ForeColor = Color.FromArgb(96, 113, 101), Margin = new Padding(0, 0, 0, 24) };
            layout.Controls.Add(eyebrow);
            layout.Controls.Add(heading);
            layout.Controls.Add(intro);

            Panel card = new Panel { BackColor = Color.White, Padding = new Padding(24), Margin = new Padding(0), AutoSize = true, Dock = DockStyle.Top };
            cardLayout = new TableLayoutPanel { AutoSize = true, Dock = DockStyle.Top, ColumnCount = 2 };
            cardLayout.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
            cardLayout.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 0));
            card.Controls.Add(cardLayout);

            Panel statusPanel = new Panel { AutoSize = true, Dock = DockStyle.Fill, Padding = new Padding(0, 4, 24, 0) };
            stateTitle = new Label { Name = "stateTitle", AutoSize = true, Text = "正在连接本机服务…", ForeColor = Color.FromArgb(22, 53, 45), Font = new Font(Font.FontFamily, 17F, FontStyle.Bold), Margin = new Padding(0, 0, 0, 10) };
            stateDetail = new Label { Name = "stateDetail", AutoSize = true, MaximumSize = new Size(390, 0), ForeColor = Color.FromArgb(100, 118, 104), Margin = new Padding(0, 0, 0, 18) };
            sourcesText = new Label { Name = "sourcesText", AutoSize = true, MaximumSize = new Size(390, 0), Text = "聊天：连接中 · 课程通知：连接中 · 作业/考试：连接中", ForeColor = Color.FromArgb(56, 91, 76), Margin = new Padding(0, 0, 0, 8) };
            countsText = new Label { Name = "countsText", AutoSize = true, MaximumSize = new Size(390, 0), Text = "已保存 0 条", ForeColor = Color.FromArgb(56, 91, 76), Margin = new Padding(0, 0, 0, 18) };
            errorText = new Label { Name = "errorText", AutoSize = true, MaximumSize = new Size(390, 0), ForeColor = Color.FromArgb(176, 53, 53), Margin = new Padding(0, 0, 0, 12) };
            timelineText = new Label { Name = "timelineText", AutoSize = true, MaximumSize = new Size(390, 0), ForeColor = Color.FromArgb(100, 118, 104), Margin = new Padding(0, 0, 0, 10) };
            errorDetail = new Label { Name = "errorDetail", AutoSize = true, MaximumSize = new Size(390, 0), ForeColor = Color.FromArgb(176, 53, 53), Margin = new Padding(0, 0, 0, 12) };
            FlowLayoutPanel buttons = new FlowLayoutPanel { AutoSize = true, MaximumSize = new Size(410, 0), FlowDirection = FlowDirection.LeftToRight, WrapContents = true, Margin = new Padding(0) };
            loginButton = MakeButton("loginButton", "扫码登录学习通", true);
            visibleLoginButton = MakeButton("visibleLoginButton", "打开官方登录窗口", false);
            visibleLoginButton.Visible = false;
            resumeButton = MakeButton("resumeButton", "恢复同步", false);
            pauseButton = MakeButton("pauseButton", "暂停同步", false);
            logoutButton = MakeButton("logoutButton", "退出账号", false);
            Button openButton = MakeButton("openInboxButton", "打开消息与任务", true);
            Button inventoryButton = MakeButton("openInventoryButton", "任务核对与补收", false);
            inventoryButton.Click += delegate { OpenLocalPage("/#sync"); };
            buttons.Controls.Add(openButton); buttons.Controls.Add(inventoryButton); buttons.Controls.Add(loginButton); buttons.Controls.Add(resumeButton); buttons.Controls.Add(pauseButton);
            FlowLayoutPanel moreButtons = new FlowLayoutPanel { AutoSize = true, MaximumSize = new Size(410, 0), WrapContents = true, Margin = new Padding(0) };
            moreButtons.Controls.Add(visibleLoginButton); moreButtons.Controls.Add(logoutButton);
            detailsPanel = new TableLayoutPanel { Name = "detailsPanel", AutoSize = true, Dock = DockStyle.Top, ColumnCount = 1, Visible = false, Margin = new Padding(0, 12, 0, 0) };
            detailsPanel.Controls.Add(timelineText); detailsPanel.Controls.Add(sourcesText); detailsPanel.Controls.Add(countsText); detailsPanel.Controls.Add(errorDetail); detailsPanel.Controls.Add(moreButtons);
            detailsToggle = new LinkLabel { Name = "detailsToggle", Text = "详细信息 ▸", AutoSize = true, LinkColor = Color.FromArgb(56, 91, 76), Margin = new Padding(0, 8, 0, 0) };
            detailsToggle.LinkClicked += delegate
            {
                detailsPanel.Visible = !detailsPanel.Visible;
                detailsToggle.Text = detailsPanel.Visible ? "收起详情 ▾" : "详细信息 ▸";
            };

            TableLayoutPanel statusLayout = new TableLayoutPanel { Dock = DockStyle.Top, AutoSize = true, ColumnCount = 1 };
            statusLayout.Controls.Add(stateTitle); statusLayout.Controls.Add(stateDetail); statusLayout.Controls.Add(errorText); statusLayout.Controls.Add(buttons); statusLayout.Controls.Add(detailsToggle); statusLayout.Controls.Add(detailsPanel);
            statusPanel.Controls.Add(statusLayout);
            statusPanel.SizeChanged += delegate
            {
                int width = Math.Max(180, statusPanel.ClientSize.Width - statusPanel.Padding.Horizontal - 8);
                foreach (Label label in new[] { stateDetail, timelineText, sourcesText, countsText, errorText, errorDetail }) label.MaximumSize = new Size(width, 0);
                buttons.MaximumSize = moreButtons.MaximumSize = new Size(width, 0);
            };

            qrPanel = new Panel { Name = "qrPanel", Dock = DockStyle.Fill, Padding = new Padding(12), BackColor = Color.FromArgb(241, 246, 240), MinimumSize = new Size(324, 324), Visible = false };
            qrPicture = new PictureBox { Name = "qrPicture", AccessibleName = "学习通官方登录二维码", Size = new Size(300, 300), SizeMode = PictureBoxSizeMode.Zoom, BackColor = Color.White, Dock = DockStyle.Fill };
            qrPanel.Controls.Add(qrPicture);
            cardLayout.Controls.Add(statusPanel, 0, 0);
            cardLayout.Controls.Add(qrPanel, 1, 0);
            layout.Controls.Add(card);

            Label warning = new Label { AutoSize = true, MaximumSize = new Size(760, 0), Text = "电脑和本软件保持运行时才会继续监测。读取学习通网页内容可能使相应消息被标记为已读。", ForeColor = Color.FromArgb(116, 123, 94), Margin = new Padding(0, 18, 0, 0) };
            layout.Controls.Add(warning);
            desktopAlertsCheck = new CheckBox { Name = "desktopAlertsCheck", Text = "桌面提醒", AutoSize = true, Enabled = false, Margin = new Padding(0, 18, 0, 4) };
            desktopAlertsDetail = new Label { Name = "desktopAlertsDetail", AutoSize = true, MaximumSize = new Size(760, 0), Text = "正在读取桌面提醒设置…", ForeColor = Color.FromArgb(96, 113, 101), Margin = new Padding(0, 0, 0, 8) };
            layout.Controls.Add(desktopAlertsCheck);
            layout.Controls.Add(desktopAlertsDetail);
            desktopAlertsCheck.CheckedChanged += delegate { if (!applyingAlertSettings && alertsController != null) alertsController.SetEnabled(desktopAlertsCheck.Checked); };

            loginButton.Click += delegate { if (controller != null) controller.Login(false); };
            visibleLoginButton.Click += delegate { if (controller != null) controller.Login(true); };
            resumeButton.Click += delegate { if (controller != null) controller.Resume(); };
            pauseButton.Click += delegate { if (controller != null) controller.Pause(); };
            logoutButton.Click += delegate
            {
                if (controller != null && MessageBox.Show(this, "退出后会清除这台电脑保存的学习通登录状态；已接收的消息和任务会保留。确定退出吗？", "退出学习通账号", MessageBoxButtons.OKCancel, MessageBoxIcon.Warning) == DialogResult.OK) controller.Logout();
            };
            openButton.Click += delegate { OpenLocalInbox(); };

            ContextMenuStrip trayMenu = new ContextMenuStrip();
            trayMenu.Items.Add("打开主窗口", null, delegate { RestoreWindow(); });
            alertsMenuItem = new ToolStripMenuItem("桌面提醒") { CheckOnClick = true, Enabled = false };
            alertsMenuItem.CheckedChanged += delegate { if (!applyingAlertSettings && alertsController != null) alertsController.SetEnabled(alertsMenuItem.Checked); };
            trayMenu.Items.Add(alertsMenuItem);
            trayMenu.Items.Add("退出软件", null, delegate { ExitApplication(); });
            tray = new NotifyIcon { Text = "CampusInbox 校园智能任务Agent", Icon = SystemIcons.Application, ContextMenuStrip = trayMenu, Visible = true };
            tray.DoubleClick += delegate { RestoreWindow(); };
            tray.BalloonTipClicked += delegate { if (activeAlertTarget != null) OpenTrustedAlert(activeAlertTarget); };
            timer = new Timer { Interval = 3000 };
            timer.Tick += delegate { if (controller != null) controller.Refresh(); };
            alertTimer = new Timer { Interval = 30000 };
            alertTimer.Tick += delegate { if (alertsController != null) alertsController.Poll(); };
            SystemEvents.PowerModeChanged += OnPowerModeChanged;
            FormClosing += OnFormClosing;
        }

        public void BindController(AppController value)
        {
            if (value == null) throw new ArgumentNullException("value");
            controller = value;
            if (Visible && IsHandleCreated) StartController();
            else Shown += StartControllerOnShown;
        }

        public void BindAlertsController(DesktopAlertController value)
        {
            if (value == null) throw new ArgumentNullException("value");
            alertsController = value;
            if (controllerStarted) { alertTimer.Start(); alertsController.Poll(); }
        }

        private void StartControllerOnShown(object sender, EventArgs args)
        {
            Shown -= StartControllerOnShown;
            StartController();
        }

        private void StartController()
        {
            if (controllerStarted || controller == null) return;
            controllerStarted = true;
            timer.Start();
            controller.Refresh();
            if (alertsController != null) { alertTimer.Start(); alertsController.Poll(); }
        }

        public void Post(Action action)
        {
            if (IsDisposed || Disposing) return;
            if (InvokeRequired) BeginInvoke(action); else action();
        }

        public void Apply(DesktopViewState state, byte[] qrPng)
        {
            stateTitle.Text = state.Title;
            stateDetail.Text = state.Summary;
            timelineText.Text = state.Detail;
            sourcesText.Text = state.SourcesText;
            countsText.Text = state.CountsText;
            errorText.Text = state.Notice ?? "";
            errorText.Visible = errorText.Text.Length > 0;
            errorDetail.Text = state.Error ?? "";
            errorDetail.Visible = errorDetail.Text.Length > 0;
            loginButton.Text = state.LoginText;
            loginButton.Visible = state.ShowLogin;
            pauseButton.Visible = state.ShowPause;
            resumeButton.Visible = state.ShowResume;
            logoutButton.Visible = state.ShowLogout;
            visibleLoginButton.Visible = state.ShowVisibleLogin;
            qrPanel.Visible = state.ShowQr;
            cardLayout.ColumnStyles[0].Width = state.ShowQr ? 52 : 100;
            cardLayout.ColumnStyles[1].SizeType = state.ShowQr ? SizeType.Percent : SizeType.Absolute;
            cardLayout.ColumnStyles[1].Width = state.ShowQr ? 48 : 0;
            SetQr(state.ShowQr ? qrPng : null);
        }

        public void ShowTransientError(string message) { errorText.Text = message; errorText.Visible = !string.IsNullOrEmpty(message); }
        public void ClearQr() { qrPanel.Visible = false; SetQr(null); }

        public void ApplyAlertSettings(bool enabled, string detail)
        {
            applyingAlertSettings = true;
            try
            {
                desktopAlertsCheck.Enabled = alertsMenuItem.Enabled = true;
                desktopAlertsCheck.Checked = alertsMenuItem.Checked = enabled;
                desktopAlertsDetail.Text = detail ?? "";
            }
            finally { applyingAlertSettings = false; }
        }

        public bool TryShowAlert(DesktopAlert alert, Uri target)
        {
            if (IsDisposed || Disposing || !tray.Visible || DateTime.UtcNow < nextAlertAt) return false;
            Uri trusted;
            if (target == null || !DesktopAlertLink.TryResolve(baseUri, target.AbsoluteUri, out trusted)) return false;
            string title = string.IsNullOrWhiteSpace(alert.Title) ? "CampusInbox 任务提醒" : alert.Title;
            string body = string.IsNullOrWhiteSpace(alert.Body) ? "点击查看任务和原始消息。" : alert.Body;
            tray.ShowBalloonTip(10000, title.Length > 63 ? title.Substring(0, 63) : title, body.Length > 255 ? body.Substring(0, 255) : body, ToolTipIcon.Info);
            activeAlertTarget = trusted;
            nextAlertAt = DateTime.UtcNow.AddSeconds(30);
            trayTipShown = true;
            return true;
        }

        private void OnPowerModeChanged(object sender, PowerModeChangedEventArgs args)
        {
            if (args.Mode != PowerModes.Resume || !IsHandleCreated || IsDisposed || Disposing) return;
            Post(delegate
            {
                if (controller != null) controller.Refresh();
                if (alertsController != null) alertsController.Poll();
            });
        }

        private void OpenTrustedAlert(Uri target)
        {
            Uri trusted;
            if (!DesktopAlertLink.TryResolve(baseUri, target.AbsoluteUri, out trusted)) return;
            try { Process.Start(new ProcessStartInfo(trusted.AbsoluteUri) { UseShellExecute = true }); }
            catch (Exception error) { desktopAlertsDetail.Text = "无法打开提醒任务：" + error.Message; }
        }

        private void SetQr(byte[] bytes)
        {
            Image previous = qrPicture.Image;
            qrPicture.Image = null;
            if (previous != null) previous.Dispose();
            if (bytes == null || bytes.Length == 0) return;
            using (MemoryStream stream = new MemoryStream(bytes))
            using (Image source = Image.FromStream(stream)) qrPicture.Image = new Bitmap(source);
        }

        private Button MakeButton(string name, string text, bool primary)
        {
            Button button = new Button { Name = name, Text = text, AutoSize = true, FlatStyle = FlatStyle.Flat, Padding = new Padding(10, 6, 10, 6), Margin = new Padding(0, 0, 9, 9), Cursor = Cursors.Hand };
            button.FlatAppearance.BorderColor = primary ? Color.FromArgb(38, 103, 78) : Color.FromArgb(205, 216, 205);
            button.BackColor = primary ? Color.FromArgb(38, 103, 78) : Color.White;
            button.ForeColor = primary ? Color.White : Color.FromArgb(36, 68, 55);
            return button;
        }

        private void OpenLocalInbox()
        {
            OpenLocalPage("/#inbox");
        }

        private void OpenLocalPage(string path)
        {
            try
            {
                ProcessStartInfo info = new ProcessStartInfo(new Uri(baseUri, path).AbsoluteUri) { UseShellExecute = true };
                Process.Start(info);
            }
            catch (Exception error) { ShowTransientError("无法打开消息界面：" + error.Message); }
        }

        private void OnFormClosing(object sender, FormClosingEventArgs args)
        {
            if (args.CloseReason != CloseReason.UserClosing)
            {
                lifetime.RequestSystemClose();
                timer.Stop();
                alertTimer.Stop();
                tray.Visible = false;
                return;
            }
            if (lifetime.RequestWindowClose()) { timer.Stop(); alertTimer.Stop(); tray.Visible = false; return; }
            args.Cancel = true;
            Hide();
            if (!trayTipShown)
            {
                trayTipShown = true;
                tray.ShowBalloonTip(2500, "CampusInbox 仍在监测", "双击托盘图标可重新打开；在托盘菜单选择“退出软件”才会停止。", ToolTipIcon.Info);
            }
        }

        private void RestoreWindow()
        {
            Show();
            WindowState = FormWindowState.Normal;
            Activate();
        }

        private void ExitApplication()
        {
            timer.Stop();
            alertTimer.Stop();
            if (controller != null) controller.Dispose();
            if (alertsController != null) alertsController.Dispose();
            lifetime.ExitFromTray();
            tray.Visible = false;
            Application.Exit();
        }

        protected override void Dispose(bool disposing)
        {
            if (disposing)
            {
                timer.Dispose();
                alertTimer.Dispose();
                SystemEvents.PowerModeChanged -= OnPowerModeChanged;
                tray.Dispose();
                Image image = qrPicture.Image;
                if (image != null) image.Dispose();
            }
            base.Dispose(disposing);
        }
    }
}
