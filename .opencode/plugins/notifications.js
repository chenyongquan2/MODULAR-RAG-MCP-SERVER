import { tool } from "@opencode-ai/plugin";

export const NotificationPlugin = async ({ $, directory }) => {
  return {
    tool: {
      notify: tool({
        description: "Send a desktop notification to the user",
        args: {
          title: tool.schema.string(),
          message: tool.schema.string(),
          priority: tool.schema.string().optional(),
        },
        async execute(args, context) {
          const { directory } = context;
          const title = args.title || "OpenCode";
          const message = args.message || "Notification";
          const priority = args.priority || "Normal";

          try {
            await $`powershell -ExecutionPolicy Bypass -File "${directory}/.opencode/hooks/windows-notification-enhanced.ps1" -Title "${title}" -Message "${message}" -Priority "${priority}"`;
            return `Notification sent: ${title} - ${message}`;
          } catch (e) {
            return `Failed to send notification: ${e}`;
          }
        },
      }),
    },
    "session.idle": async (input) => {
      const { session } = input;
      if (session && session.summary) {
        await $`powershell -ExecutionPolicy Bypass -File "${directory}/.opencode/hooks/windows-notification-enhanced.ps1" -Title "OpenCode 任务完成" -Message "任务已完成，请查看终端" -Priority "Normal"`;
      }
    },
  };
};
