/* Cloudmorrow on the phone: the same notes and Quills the TUI shows.

   This file is only the list of features. Each is a file of its own that
   registers its screens and its tab with core.js; the order here is the
   order of the tabs. A new feature is a new file and one line below. */

import "./install.js";
import "./login.js";
import "./today.js";
import "./quills.js";
import "./chat.js";
import "./calendar.js";
import "./format.js";
import "./features.js";
import "./me.js";
import "./admin.js";
import "./quillsadmin.js";
import "./push.js";
import "./desktop.js";
import "./desktopbridge.js";
import "./fresh.js";
import { start } from "./core.js";

start();
