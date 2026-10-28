using System;
using System.Collections.Generic;
using System.Globalization;

namespace CourseInbox.Desktop
{
    public static class DesktopPresenter
    {
        private static readonly IDictionary<string, string> Titles = new Dictionary<string, string>
        {
            { "idle", "尚未登录" },
            { "connecting", "正在连接" },
            { "waiting_scan", "等待扫码" },
            { "connected", "正在监测" },
            { "syncing", "正在监测" },
            { "expired", "登录已失效" },
            { "paused", "同步已暂停" },
            { "error", "连接需要处理" },
            { "retrying", "网络波动正在重试" },
            { "partial", "部分消息待重试" }
        };

        private static readonly IDictionary<string, string> SourceTitles = new Dictionary<string, string>
        {
            { "idle", "尚未连接" },
            { "connecting", "连接中" },
            { "syncing", "读取中" },
            { "connected", "已同步" },
            { "retrying", "待重试" },
            { "partial", "部分待重试" },
            { "expired", "需重新扫码" },
            { "error", "需处理" }
        };

        public static DesktopViewState From(DesktopStatus status, DesktopCounts counts)
        {
            if (status == null) throw new ArgumentNullException("status");
            counts = counts ?? new DesktopCounts();
            DesktopViewState view = new DesktopViewState();
            string state = status.State ?? "";
            string title;
            bool known = Titles.TryGetValue(state, out title);
            view.Title = known ? title : "连接需要处理";
            view.Error = status.LastError ?? "";
            if (!known && view.Error.Length == 0) view.Error = "服务器返回了未知状态，请重试连接。";
            if (view.Error.Length == 0 && status.Queued > 0) view.Error = "有 " + status.Queued + " 条消息等待补传。";
            switch (state)
            {
                case "idle": view.Summary = "登录学习通后，自动接收消息与任务。"; break;
                case "waiting_scan": view.Summary = "使用学习通扫描右侧二维码。"; break;
                case "connecting": view.Summary = "正在连接学习通，请稍候。"; break;
                case "paused": view.Summary = "已保存的消息和任务仍可查看。"; break;
                case "expired": view.Summary = "请重新扫码，继续接收消息。"; break;
                case "retrying": view.Summary = "后台正在重试，已收到的消息会保留。"; break;
                case "partial": view.Summary = "部分内容待补收，展开详细信息查看。"; break;
                case "connected":
                case "syncing": view.Summary = "新消息会自动保存，任务仍需确认。"; break;
                default: view.Summary = "请展开详细信息查看连接问题。"; break;
            }
            view.Notice = view.Error.Length == 0 ? "" :
                (view.Error.Contains("附件或图片") ? "部分附件或图片待核对，详情见下方。" :
                (status.Queued > 0 && string.IsNullOrEmpty(status.LastError) ? view.Error : "同步有待处理事项，请展开详细信息。"));
            List<string> detail = new List<string>();
            if (!string.IsNullOrEmpty(status.LastChecked)) detail.Add("最近检查 " + TimeText(status.LastChecked));
            if (!string.IsNullOrEmpty(status.LastReceived)) detail.Add("最近收到 " + TimeText(status.LastReceived));
            view.Detail = detail.Count == 0 ? "新消息会自动进入本地收件箱，任务仍需确认。" : string.Join(" · ", detail.ToArray());
            view.ShowQr = state == "waiting_scan" && status.QrReady;
            view.ShowLogin = state == "idle" || state == "waiting_scan" || state == "expired" || (state == "error" && !status.SessionSaved);
            view.LoginText = state == "waiting_scan" ? "重新获取二维码" : (state == "expired" || status.SessionSaved ? "重新扫码" : "扫码登录学习通");
            view.ShowPause = status.Enabled && state != "idle" && state != "paused";
            view.ShowResume = status.SessionSaved && (!status.Enabled || state == "paused" || state == "retrying" || state == "partial" || state == "error" || !known);
            view.ShowLogout = status.SessionSaved;
            view.ShowVisibleLogin = state == "connecting" || state == "waiting_scan" || state == "expired" || state == "error";
            view.SourcesText = SourceText(status);
            view.CountsText = "已保存 " + counts.Received + " 条 · 聊天 " + counts.Chat + " · 课程通知 " + counts.CourseNotice + " · 作业/考试 " + counts.TaskCenter;
            return view;
        }

        private static string SourceText(DesktopStatus status)
        {
            if (!status.Enabled) return "聊天：已暂停 · 课程通知：已暂停 · 作业/考试：已暂停";
            return "聊天：" + SourceState(status, "chat") + " · 课程通知：" + SourceState(status, "notice") + " · 作业/考试：" + SourceState(status, "task_center");
        }

        private static string SourceState(DesktopStatus status, string name)
        {
            DesktopSourceStatus source;
            if (status.Sources == null || !status.Sources.TryGetValue(name, out source) || source == null) return "连接中";
            string text;
            text = SourceTitles.TryGetValue(source.State ?? "", out text) ? text : "需处理";
            List<string> detail = new List<string>();
            if (source.PendingCount > 0) detail.Add("待检查/重试 " + source.PendingCount);
            if (!string.IsNullOrEmpty(source.IssueSummary)) detail.Add(source.IssueSummary);
            if (source.CheckedCount > 0) detail.Add("本轮读取 " + source.CapturedCount + "/" + source.CheckedCount);
            if (source.FailedCount > 0) detail.Add("本轮未读 " + source.FailedCount);
            string stage = StageText(source.Stage);
            if (stage.Length > 0) detail.Add(stage);
            if (!string.IsNullOrEmpty(source.LastSuccess)) detail.Add("完整读取 " + TimeText(source.LastSuccess));
            if (detail.Count == 0 && !string.IsNullOrEmpty(source.LastChecked)) detail.Add("检查 " + TimeText(source.LastChecked));
            return detail.Count == 0 ? text : text + "（" + string.Join(" · ", detail.ToArray()) + "）";
        }

        private static string TimeText(string value)
        {
            DateTimeOffset parsed;
            return DateTimeOffset.TryParse(value, CultureInfo.InvariantCulture, DateTimeStyles.RoundtripKind, out parsed) ? parsed.ToLocalTime().ToString("HH:mm") : value;
        }

        private static string StageText(string stage)
        {
            switch (stage)
            {
                case "detail_content": return "通知正文待重试";
                case "detail_parse": return "通知正文结构待核对";
                case "chat_content": return "聊天内容待重试";
                case "chat_conversation": return "聊天会话待重试";
                case "task_navigation": return "课程入口待重试";
                case "task_list": return "作业/考试列表待重试";
                default: return "";
            }
        }
    }
}
