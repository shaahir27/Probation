/**
 * Hash routing with browser history and URL-persisted filters.
 *
 * A query string after the path (`#/queue?gate=ask`) survives refresh and Back.
 * Route objects stay exactly the shape the tests assert, so a query is attached
 * only when one was actually present.
 */

export type PrimaryRoute = "home" | "queue" | "watching" | "actions" | "permissions";

export type RouteQuery = Record<string, string>;

export type Route =
  | { page: PrimaryRoute; query?: RouteQuery }
  | { page: "more"; section?: string; query?: RouteQuery }
  | { page: "item" | "watching-item"; id: string; query?: RouteQuery }
  | { page: "request"; id: string; query?: RouteQuery }
  | { page: "not-found"; query?: RouteQuery };

const primary = new Set<PrimaryRoute>(["home", "queue", "watching", "actions", "permissions"]);

/** Every destination the More section router can render. */
export const moreSections = new Set([
  "insights",
  "metrics",
  "habits",
  "chains",
  "exams",
  "connections",
  "usage",
  "privacy",
  "activity",
  "settings",
  "help",
  "radar",
  "library",
]);

export const QUEUE_GATES = ["all", "ask", "suggest"] as const;
export type QueueGate = (typeof QUEUE_GATES)[number];

function decode(segment: string): string | null {
  try {
    return decodeURIComponent(segment);
  } catch {
    return null;
  }
}

export function parseQuery(search: string): RouteQuery {
  const params = new URLSearchParams(search.startsWith("?") ? search.slice(1) : search);
  const output: RouteQuery = {};
  params.forEach((value, key) => {
    if (/^[a-z][a-z0-9_-]{0,31}$/.test(key)) output[key] = value.slice(0, 200);
  });
  return output;
}

function withQuery(route: Route, query: RouteQuery | null): Route {
  if (query === null) return route;
  return { ...route, query } as Route;
}

export function parseRoute(hash: string): Route {
  const [pathWithSlash, search] = hash.replace(/^#\/?/, "").split("?");
  const path = pathWithSlash.replace(/\/$/, "");
  const parts = path.split("/").filter(Boolean).map(decode);
  const query = search !== undefined && search !== "" ? parseQuery(search) : null;
  if (parts.some((part) => part === null)) return withQuery({ page: "not-found" }, query);
  const [first, second] = parts as string[];
  if (!first) return withQuery({ page: "home" }, query);
  if (first === "queue" || first === "watching") {
    if (second && parts.length === 2) return withQuery({ page: first === "queue" ? "item" : "watching-item", id: second }, query);
    return parts.length === 1 ? withQuery({ page: first }, query) : withQuery({ page: "not-found" }, query);
  }
  if (first === "more") {
    if (!second && parts.length === 1) return withQuery({ page: "more" }, query);
    return second && parts.length === 2 && moreSections.has(second)
      ? withQuery({ page: "more", section: second }, query)
      : withQuery({ page: "not-found" }, query);
  }
  if (primary.has(first as PrimaryRoute)) {
    return parts.length === 1 ? withQuery({ page: first as PrimaryRoute }, query) : withQuery({ page: "not-found" }, query);
  }
  if (first === "requests" && second && parts.length === 2) return withQuery({ page: "request", id: second }, query);
  return withQuery({ page: "not-found" }, query);
}

function queryString(query?: RouteQuery): string {
  if (!query) return "";
  const params = new URLSearchParams();
  Object.entries(query).forEach(([key, value]) => params.set(key, value));
  const text = params.toString();
  return text ? `?${text}` : "";
}

export function routeHash(route: Route): string {
  const suffix = queryString(route.query);
  switch (route.page) {
    case "item":
      return `#/queue/${encodeURIComponent(route.id)}${suffix}`;
    case "watching-item":
      return `#/watching/${encodeURIComponent(route.id)}${suffix}`;
    case "request":
      return `#/requests/${encodeURIComponent(route.id)}${suffix}`;
    case "more":
      return route.section ? `#/more/${encodeURIComponent(route.section)}${suffix}` : `#/more${suffix}`;
    case "not-found":
      return `#/not-found${suffix}`;
    default:
      return `#/${route.page}${suffix}`;
  }
}

/** Pushes a new history entry so Back returns to the previous screen and filters. */
export function navigate(route: Route): void {
  const next = routeHash(route);
  if (window.location.hash === next) window.dispatchEvent(new HashChangeEvent("hashchange"));
  else window.location.hash = next;
}

export function primaryPage(route: Route): PrimaryRoute | "more" {
  if (route.page === "item") return "queue";
  if (route.page === "watching-item") return "watching";
  if (route.page === "request") return "actions";
  if (route.page === "not-found") return "home";
  return route.page;
}

export function queueGate(route: Route): QueueGate {
  const value = route.query?.gate;
  return QUEUE_GATES.includes(value as QueueGate) ? (value as QueueGate) : "all";
}

/** Rewrites only the filters of the current route, keeping Back intact. */
export function setQueryFilter(route: Route, key: string, value: string | null): Route {
  const query: RouteQuery = { ...(route.query ?? {}) };
  if (value === null) delete query[key];
  else query[key] = value;
  const next = { ...route } as Route;
  if (Object.keys(query).length === 0) delete (next as { query?: RouteQuery }).query;
  else (next as { query?: RouteQuery }).query = query;
  return next;
}
