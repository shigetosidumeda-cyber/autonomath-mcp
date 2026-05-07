export default {
  async fetch(request) {
    const url = new URL(request.url);
    const redirectHosts = new Set([
      "www.jpcite.com",
      "zeimu-kaikei.ai",
      "www.zeimu-kaikei.ai",
    ]);
    if (!redirectHosts.has(url.hostname)) {
      return new Response("not found", { status: 404 });
    }
    url.hostname = "jpcite.com";
    return Response.redirect(url.toString(), 301);
  },
};
