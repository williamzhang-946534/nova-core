import { expect, test, vi } from "vitest";

import { playTtsAudio } from "./useVoiceInteraction";

const createObjectURL = vi.fn(() => "blob:audio");
const revokeObjectURL = vi.fn();
const play = vi.fn();

class FakeAudio {
  onended: (() => void) | null = null;
  onerror: (() => void) | null = null;
  play() {
    return play.call(this);
  }
}

play.mockImplementation(function (this: FakeAudio) {
  return Promise.resolve().then(() => this.onended?.());
});

vi.stubGlobal(
  "URL",
  class {
    static createObjectURL = createObjectURL;
    static revokeObjectURL = revokeObjectURL;
  },
);
vi.stubGlobal("Audio", FakeAudio);
vi.stubGlobal(
  "fetch",
  vi.fn().mockResolvedValue({
    ok: true,
    blob: () => Promise.resolve(new Blob(["audio"], { type: "audio/wav" })),
  }),
);

test("tts object URLs are released after playback", async () => {
  await playTtsAudio("asset-1");

  expect(createObjectURL).toHaveBeenCalledTimes(1);
  expect(play).toHaveBeenCalledTimes(1);
  expect(revokeObjectURL).toHaveBeenCalledWith("blob:audio");
});
