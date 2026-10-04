// Route table: hash path -> page module. Each page exports { title, render(view, ctx, params) }.
import analyst from "./analyst.js";
import events from "./events.js";
import incidents from "./incidents.js";
import integration from "./integration.js";
import lab from "./lab.js";
import overview from "./overview.js";
import simulation from "./simulation.js";
import users from "./users.js";

export const PAGES = { overview, events, incidents, users, lab, simulation, integration, analyst };

// Two-key shortcuts: "g" then a letter.
export const SHORTCUTS = { o: "overview", e: "events", i: "incidents", c: "users", l: "lab", s: "simulation", n: "integration", a: "analyst" };
