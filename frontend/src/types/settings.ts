import type { SystemSettings, WebConsoleSettings } from "./console";

export type { SystemSettings, WebConsoleSettings };
export type SystemSettingsResponse = { data: SystemSettings };
export type SystemSettingsUpdateRequest = { web_console: WebConsoleSettings };
