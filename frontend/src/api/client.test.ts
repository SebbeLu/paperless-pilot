import { ApiError, unwrap } from "./client";

const response = (status: number) => new Response(null, { status });

describe("unwrap", () => {
  it("liefert Daten bei Erfolg", async () => {
    await expect(
      unwrap(Promise.resolve({ data: { ok: 1 }, response: response(200) })),
    ).resolves.toEqual({
      ok: 1,
    });
  });

  it.each([
    [{ detail: "Dokument fehlt" }, "Dokument fehlt"],
    [{ detail: [{ msg: "Value error, A" }, { msg: "B" }, {}] }, "A · B"],
    [{ detail: 42 }, "Backend antwortet mit HTTP 404"],
    [undefined, "Backend antwortet mit HTTP 404"],
  ])("übersetzt Fehler %j", async (error, message) => {
    const failing = unwrap(Promise.resolve({ error, response: response(404) }));
    await expect(failing).rejects.toBeInstanceOf(ApiError);
    await expect(failing).rejects.toMatchObject({ message, status: 404 });
  });
});
