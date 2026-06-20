addEventListener('fetch', function(event) {
  if (event.request.method === 'POST') {
    return event.respondWith(handleRequest(event));
  }
  return event.respondWith(new Response('Method not allowed', { status: 405 }));
});

async function handleRequest(event) {
  return new Response(JSON.stringify({ reply: "Hello from CF!" }), {
    headers: { "Content-Type": "application/json" },
  });
}
