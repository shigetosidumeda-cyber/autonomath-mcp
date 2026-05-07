export default {
  async fetch(request) {
    const url = new URL(request.url);
    if (url.hostname !== "www.jpcite.com") {
      return new Response("not found", { status: 404 });
    }
    url.hostname = "jpcite.com";
    return Response.redirect(url.toString(), 301);
  },
};
