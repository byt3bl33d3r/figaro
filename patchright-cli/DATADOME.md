# DataDome Bot Detection — Reverse Engineering Findings

Research conducted against `fastpeoplesearch.com` using patchright-cli in a containerized Linux environment (Xvfb + headless Chromium).

## Detection Architecture

The site uses a **dual-layer** detection system:

1. **DataDome** (primary) — server-side + client-side fingerprinting, captcha delivery
2. **Cloudflare Bot Management** — proof-of-work challenge in a hidden 1x1 iframe (`/cdn-cgi/challenge-platform/scripts/jsd/main.js`)

## How the Block Decision Is Made

The initial request receives a **403 immediately** — the server decides the client is a bot *before any client-side JS runs*. The 403 response includes:

- `x-datadome: protected` / `x-dd-b: 1` — DataDome protection headers
- `dd.rt = "c"` — response type "captcha" (challenge required)
- `dd.t = "fe"` — "frontend enforcement" (show captcha to user)
- `dd.s = 50779` — the **bot signal score** (higher = more suspicious)
- `dd.e` — encrypted server-side payload (challenge parameters)
- `dd.cid` — client ID for session tracking
- `dd.hsh` — hash for popup permission decisions

The `accept-ch` response header requests Client Hints: `Sec-CH-UA`, `Sec-CH-UA-Mobile`, `Sec-CH-UA-Platform`, `Sec-CH-UA-Arch`, `Sec-CH-UA-Full-Version-List`, `Sec-CH-UA-Model`, `Sec-CH-Device-Memory`.

## Server-Side Detection Vectors (Pre-JS)

These are evaluated on the first HTTP request, before any JavaScript executes:

| Signal | Our Value | Risk | Notes |
|--------|-----------|------|-------|
| **TLS Fingerprint (JA3)** | `adc28228e4ea39da92824ebcd5d2bb7b` | CRITICAL | Maps to Chromium automation in DataDome's DB |
| **TLS Fingerprint (JA4)** | `t13d1516h2_8daaf6152771_d8a2da3f94cd` | CRITICAL | Cipher suite order + extensions are deterministic per build |
| **HTTP/2 Fingerprint** | `52d84b11737d980aef856699f885ca86` (`1:65536;2:0;4:6291456;6:262144`) | CRITICAL | SETTINGS frame matches Playwright/Chromium profile |
| **Client Hints (Sec-CH-UA)** | `Chromium/145` + `Not:A-Brand/99` — missing `Google Chrome` brand | HIGH | Raw Chromium = automation tooling |
| **IP Reputation** | `REDACTED` | VARIABLE | DataDome maintains IP/ASN reputation databases |
| **Missing `datadome` Cookie** | No cookie (first visit) | MEDIUM | Forces fresh evaluation; no prior device fingerprint |

### TLS Fingerprint (JA3/JA4)

```
ja3_hash:  adc28228e4ea39da92824ebcd5d2bb7b
ja4:       t13d1516h2_8daaf6152771_d8a2da3f94cd
ja3_text:  771,4865-4866-4867-49195-49199-49196-49200-52393-52392-49171-49172-156-157-47-53,...
```

Chromium's TLS stack produces a well-known JA3 hash. DataDome maintains a database mapping JA3/JA4 fingerprints to known automation tools. The cipher suite order, extensions, and elliptic curves in the TLS ClientHello are deterministic per browser build.

### HTTP/2 Fingerprint

```
akamai_hash: 52d84b11737d980aef856699f885ca86
akamai_text: 1:65536;2:0;4:6291456;6:262144|15663105|0|m,a,s,p
```

The HTTP/2 SETTINGS frame (initial window size, header table size, max concurrent streams, stream priorities) uniquely identifies the HTTP client implementation. Playwright/Chromium has a distinct H2 fingerprint that differs from standard Chrome.

### Client Hints (Sec-CH-UA)

```json
{
  "brands": [
    {"brand": "Chromium", "version": "145"},
    {"brand": "Not:A-Brand", "version": "99"}
  ],
  "mobile": false,
  "platform": "Linux"
}
```

Missing `Google Chrome` brand — only `Chromium` + `Not:A-Brand`. A real Chrome install includes a `Google Chrome` brand entry. This signals a raw Chromium build (i.e., automation tooling).

### IP Reputation

DataDome maintains IP reputation databases. The detected IP may have existing bot activity history. Combined with other signals, a neutral IP still gets flagged; a bad-reputation IP gets blocked outright.

### Missing `datadome` Cookie

First visit = no cookie. DataDome uses the cookie to track device fingerprints across requests. No prior cookie forces a fresh evaluation — combined with suspicious server-side signals, this triggers the challenge.

## Client-Side Detection Vectors (Post-JS)

Once the captcha page loads, DataDome's `c.js` tag and the captcha iframe collect additional fingerprints:

| Signal | Our Value | Risk | Notes |
|--------|-----------|------|-------|
| **WebGL Renderer** | `ANGLE (Google, Vulkan 1.3.0 (SwiftShader Device (LLVM 16.0.0) (0x0000C0DE)), SwiftShader driver)` | CRITICAL | Software GPU = headless/container. Real users have hardware GPUs. |
| **WebGL Max Texture Size** | `8192` | HIGH | SwiftShader limit; real GPUs report 16384+ |
| **WebGL Extension Count** | `35` | MEDIUM | Real GPUs typically have 40+ |
| **Color Depth** | `16` (pixelDepth: `16`) | HIGH | Xvfb default; real displays are 24-bit or 32-bit |
| **Stack Traces** | `UtilityScript.evaluate` in `Error().stack` | HIGH | Playwright/Patchright execution wrapper leaked |
| **Timezone** | `UTC` (offset: `0`) | MEDIUM | Unusual for US-targeted site; containers default to UTC |
| **Fonts — Verdana** | NOT detected | MEDIUM | Common font missing in container |
| **Fonts — Georgia** | NOT detected | MEDIUM | Common font missing in container |
| **Speech Synthesis Voices** | `0` voices | MEDIUM | Real Chrome has 20+; zero = headless/container |
| **WebRTC Adapters** | "No available adapters" | MEDIUM | STUN/ICE fails in container networking |
| **`chrome.runtime`** | `undefined` | LOW-MEDIUM | Real Chrome has it from default extensions |
| **Bluetooth API** | `undefined` | LOW | Missing in containers; weak signal alone |
| **Media Devices** | API present, no real devices | LOW | `enumerateDevices()` returns empty or virtual-only |
| **`navigator.webdriver`** | `false` | PASS | Patchright hides this correctly |
| **`window.chrome`** | Present (`loadTimes`, `csi`, `app`) | PASS | Looks normal |
| **`$cdc_` / `__selenium` globals** | None | PASS | No automation framework leaks |
| **`Function.prototype.toString`** | `[native code]` | PASS | No monkey-patching |
| **`navigator.plugins`** | 5 | PASS | Reasonable count |
| **`navigator.languages`** | `["en-US", "en"]` | PASS | Normal |
| **`navigator.hardwareConcurrency`** | `16` | PASS | Plausible |
| **`navigator.deviceMemory`** | `8` GB | PASS | Plausible |
| **`outerWidth/Height` vs `innerWidth/Height`** | `1440x742` vs `1440x655` | PASS | Difference suggests real window chrome |
| **`eval.toString()`** | `[native code]` | PASS | Clean |
| **`navigator.webdriver` descriptor** | Native getter, configurable, enumerable | PASS | Matches real Chrome |

### WebGL Renderer (CRITICAL)

```
ANGLE (Google, Vulkan 1.3.0 (SwiftShader Device (LLVM 16.0.0) (0x0000C0DE)), SwiftShader driver)
```

SwiftShader is a CPU-based software GPU renderer. Real users have hardware GPUs (NVIDIA, AMD, Intel). SwiftShader is a dead giveaway for headless/containerized environments. DataDome checks `WEBGL_debug_renderer_info` extension parameters `UNMASKED_VENDOR_WEBGL` (37445) and `UNMASKED_RENDERER_WEBGL` (37446).

Additional WebGL signals collected:
- `gl.RENDERER`: "WebKit WebGL"
- `gl.VERSION`: "WebGL 1.0 (OpenGL ES 2.0 Chromium)"
- `MAX_TEXTURE_SIZE`: 8192 (SwiftShader limit; real GPUs report 16384+)
- Extension count: 35 (real GPUs typically have 40+)

### Color Depth (HIGH)

```
screen.colorDepth: 16
screen.pixelDepth: 16
```

Xvfb (virtual framebuffer) defaults to 16-bit color depth. Real displays are 24-bit or 32-bit. This is a strong signal for a virtual display environment.

### Stack Traces — UtilityScript Leak (HIGH)

```
TypeError: Cannot read properties of null (reading '0')
    at eval (eval at evaluate (:290:30), <anonymous>:5:11)
    at eval (<anonymous>)
    at UtilityScript.evaluate (<anonymous>:290:30)
    at UtilityScript.<anonymous> (<anonymous>:1:44)
```

Playwright/Patchright wraps all `page.evaluate()` calls in a `UtilityScript` context. Any `Error().stack` captured during execution reveals this. DataDome's tag can intentionally trigger an error and inspect the stack trace for automation framework signatures.

### Timezone (MEDIUM)

```
Intl.DateTimeFormat().resolvedOptions().timeZone: "UTC"
new Date().getTimezoneOffset(): 0
```

UTC timezone for a US-targeted people search site is unusual. Most real US users are in EST/CST/MST/PST. Containers default to UTC unless explicitly configured.

### Missing Fonts (MEDIUM)

```
Arial:           detected
Verdana:         NOT detected
Times New Roman: detected
Georgia:         NOT detected
Courier New:     detected
```

Containerized Linux environments have minimal font packages. Missing common fonts like Verdana and Georgia signal a stripped-down OS.

### Speech Synthesis Voices (MEDIUM)

```
speechSynthesis.getVoices().length: 0
```

Real Chrome on desktop systems has 20+ speech synthesis voices. Zero voices indicates a headless or containerized environment without audio/speech support.

### `chrome.runtime` (LOW-MEDIUM)

```
window.chrome.runtime: undefined
```

Real Chrome has `chrome.runtime` populated by default extensions. Automation Chromium strips extensions, leaving `chrome.runtime` absent. Present `chrome` keys: `loadTimes`, `csi`, `app`.

### Bluetooth API (LOW)

```
navigator.bluetooth: undefined
```

Real Chrome on most platforms exposes the Bluetooth API. Missing in containerized environments. Weak signal individually but adds to the cumulative score.

### WebRTC / Network Adapter Detection (MEDIUM)

The captcha page's console outputs:

```
No available adapters.
```

This comes from `adapter.js` (WebRTC adapter shim) loaded within the captcha iframe. DataDome uses WebRTC for multiple detection purposes:

1. **ICE Candidate Harvesting** — `RTCPeerConnection` with a STUN server reveals the client's local IP addresses (including private RFC1918 addresses like `192.168.x.x`, `10.x.x.x`). Containers and VPNs produce unusual IP patterns (e.g., Docker bridge `172.17.x.x`) that don't match residential networks.

2. **STUN/TURN Connectivity** — If STUN binding requests fail or return unexpected results, it signals a restricted network environment (corporate proxy, datacenter, container without full network stack).

3. **Media Device Enumeration** — `navigator.mediaDevices.enumerateDevices()` reveals available cameras and microphones. Real desktops have audio/video devices; containers typically have none or only virtual devices.

4. **Adapter Availability** — The "No available adapters" message means the WebRTC adapter library couldn't find a compatible WebRTC implementation or the environment lacks the necessary network interfaces. In a container with limited networking, the STUN/TURN negotiation fails, producing this error.

5. **IP Consistency Check** — The public IP seen by the web server should match the IP resolved via STUN. VPNs and proxies create mismatches that DataDome can detect.

While `RTCPeerConnection` is technically available (`typeof RTCPeerConnection !== "undefined"` returns `true`), the actual ICE candidate gathering fails or produces container-specific network topology signatures.

## Container Mitigation Analysis

Of the 12 failing client-side signals, 7 are fixable with config changes or moderate code work. The 3 easy config fixes (color depth, timezone, fonts) are the highest ROI — zero code changes, eliminating 3 medium-to-high risk signals.

However, none of this matters much if the **server-side signals** (TLS fingerprint, H2 fingerprint, missing Chrome brand in Client Hints) are the primary trigger. Those are baked into Chromium's network stack and can't be changed without a custom build or external proxy that rewrites the TLS ClientHello.

| # | Signal | Risk | Fixable? | How |
|---|--------|------|----------|-----|
| 1 | **WebGL Renderer** (SwiftShader) | CRITICAL | **Already done** | `--webgl-renderer` flag exists in patchright-cli; route-based injection patches `getParameter` for 37445/37446 |
| 2 | **WebGL Max Texture Size** (8192) | HIGH | **Yes — code change** | Extend the existing route injection to also patch `getParameter` for `MAX_TEXTURE_SIZE` → return 16384 |
| 3 | **WebGL Extension Count** (35) | MEDIUM | **Yes — code change** | Patch `getSupportedExtensions()` in the same route injection to append known extensions |
| 4 | **Color Depth** (16-bit) | HIGH | **Yes — config** | Start Xvfb with `-screen 0 1920x1080x24` instead of default 16-bit |
| 5 | **Stack Traces** (UtilityScript) | HIGH | **N/A in practice** | UtilityScript only appears in stacks from `page.evaluate()` calls. DataDome's own scripts run from `<script>` tags and won't see it in their `new Error().stack`. Not a real detection vector unless we call evaluate during page load. |
| 6 | **Timezone** (UTC) | MEDIUM | **Yes — env var** | `TZ=America/New_York` before launching the browser |
| 7 | **Fonts** (Verdana, Georgia missing) | MEDIUM | **Yes — apt install** | `apt install fonts-liberation fonts-dejavu fonts-crosextra-carlito fonts-crosextra-caladea` or the MS core fonts |
| 8 | **Speech Synthesis Voices** (0) | MEDIUM | **Difficult** | Needs `speech-dispatcher` + `espeak-ng` installed and running. Even then, Chrome may not pick them up without a running PulseAudio session. |
| 9 | **WebRTC Adapters** | MEDIUM | **Partial** | Depends on fixing media devices + network config. Virtual network interfaces could help ICE candidates look more normal, but STUN results will still expose datacenter IP. |
| 10 | **`chrome.runtime`** | LOW-MEDIUM | **Yes — code change** | Inject via route-based HTML injection (same mechanism as WebGL spoofing). Add a script that creates `window.chrome.runtime = {connect: function(){}, sendMessage: function(){}}` |
| 11 | **Bluetooth API** | LOW | **No** | Needs a real Bluetooth stack or deep shimming of the `navigator.bluetooth` API. Not worth the complexity for a low signal. |
| 12 | **Media Devices** | LOW | **Difficult** | Need PulseAudio + virtual audio sink for microphone, v4l2loopback for camera. Doable but heavy container setup. |

### Fixability Summary

| Category | Count | Signals |
|----------|-------|---------|
| Already implemented | 1 | WebGL renderer |
| Easy fix (config/env) | 3 | Color depth, timezone, fonts |
| Code change (route injection) | 3 | WebGL texture size, WebGL extensions, `chrome.runtime` |
| Not a real vector | 1 | UtilityScript stack traces |
| Difficult but possible | 2 | Speech synthesis, media devices |
| Not practical | 2 | Bluetooth, WebRTC (STUN will always expose datacenter IP) |

## The DataDome Captcha Flow

1. **Server returns 403** with inline `dd` config object containing `cid`, `hash`, encrypted challenge `e`, and bot score `s`
2. **`c.js` tag** loads from `ct.captcha-delivery.com`:
   - Manages the captcha iframe lifecycle
   - Tracks and persists `document.referrer` in `sessionStorage`
   - Probes cookie domain candidates (generates 2-8 variations)
   - Validates postMessage origins against `.datado.me` and `.captcha-delivery.com`
   - Handles post-solve navigation (reload, go-back, or form replay)
3. **Captcha iframe** loads from `geo.captcha-delivery.com` (cross-origin, parent cannot inspect):
   - Presents slider CAPTCHA ("Slide right to secure your access")
   - Offers audio CAPTCHA alternative (6-digit code)
   - Collects device fingerprints via `userEnv` parameter
   - Sends `XMLHttpRequest` with `cid`, `userEnv` hash, challenge tokens, referer, UA, and X-Forwarded-For
   - Calls `window.captchaCallback()` on solve
4. **Cloudflare challenge** runs in a hidden 1x1 iframe:
   - Loads `/cdn-cgi/challenge-platform/scripts/jsd/main.js`
   - Performs proof-of-work computation
   - POSTs result to `/cdn-cgi/challenge-platform/h/b/jsd/oneshot/{ray_id}/...`
   - Additional environment fingerprinting
5. On successful solve, the iframe sends postMessage to `c.js`, which sets the `datadome` cookie and navigates (reload/back/form-replay)

### DevTools Detection

The captcha page actively detects open DevTools:

```
Warning: Please close the DevTools panel before solving the captcha!
```

DataDome will refuse to validate the CAPTCHA if DevTools is open. Detection methods include:
- Timing-based: `debugger` statement execution time differential
- Console side-channel: logging objects with custom getters that fire when DevTools inspects them
- Window dimension delta: `window.outerHeight - window.innerHeight > threshold` (DevTools panel takes space)

## Summary: Detection Signal Hierarchy

### Tier 1 — Instant Block (Server-Side, Pre-JS)
- TLS fingerprint (JA3/JA4) matching known automation tools
- HTTP/2 SETTINGS frame fingerprint
- Missing/wrong Client Hints (`Sec-CH-UA` without `Google Chrome` brand)
- IP reputation + datacenter/hosting ASN detection

### Tier 2 — High Confidence Bot Signals (Client-Side)
- SwiftShader WebGL renderer
- `UtilityScript` in error stack traces
- 16-bit color depth (Xvfb)
- WebRTC adapter failures / container network topology

### Tier 3 — Corroborating Signals (Client-Side)
- UTC timezone for locale-specific site
- Missing fonts (Verdana, Georgia)
- Zero speech synthesis voices
- Missing `chrome.runtime`
- Missing Bluetooth API
- Media device enumeration (no cameras/microphones)

### Tier 4 — Behavioral (Not Triggered in This Test)
- Mouse movement patterns / absence
- Slider drag dynamics (speed, acceleration, jitter)
- Keyboard timing patterns
- Page interaction cadence
- Rapid repeated requests

DataDome's scoring is cumulative — Tier 1 signals trigger the challenge, Tier 2-3 signals inform whether the captcha solve should be trusted, and Tier 4 signals are evaluated during captcha interaction itself.
