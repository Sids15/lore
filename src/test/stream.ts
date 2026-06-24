/** Test helpers: build minimal `Response`-like objects for a mocked `fetch`. */

/** A streaming response whose body yields the given string chunks as bytes. */
export function streamResponse(
  chunks: string[],
  init: { ok?: boolean; status?: number } = {},
): Response {
  const encoder = new TextEncoder();
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
      controller.close();
    },
  });
  return {
    ok: init.ok ?? true,
    status: init.status ?? 200,
    body,
  } as unknown as Response;
}

/** A plain JSON response (for non-streaming endpoints / error bodies). */
export function jsonResponse(
  data: unknown,
  init: { ok?: boolean; status?: number } = {},
): Response {
  return {
    ok: init.ok ?? true,
    status: init.status ?? 200,
    json: async () => data,
  } as unknown as Response;
}
