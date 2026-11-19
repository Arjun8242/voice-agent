/**
 * The characters of the viva! design (docs/viva-landing.html, docs/viva-design-blobs.html): Sapwa (the neutral
 * interviewer), Sheru Bhai (the strict one) and the rep (recruiter mode), drawn as SVG markup.
 * Character.svelte animates them by class name: body, pupils, lids, smile, open, mo, tongue, ears, think.
 * The markup is fixed text from this file, never visitor input, so it is safe to render with {@html}.
 */

export type CharacterKey = 'sapwa' | 'sheru' | 'rep';

export interface CharacterLook {
  name: string;
  color: string; // the character's main colour, used for accents around it
  soft: string; // a pale background that goes with it
  vibe: string;
}

export const CHARACTERS: Record<CharacterKey, CharacterLook> = {
  sapwa: { name: 'Sapwa', color: '#9ccc4a', soft: '#e6f4cf', vibe: 'master ji · gives hints' },
  sheru: { name: 'Sheru Bhai', color: '#e2b25e', soft: '#fff0cf', vibe: 'boss energy · no hints' },
  rep: { name: "Arjun's Rep", color: '#7fd4ff', soft: '#dff3ff', vibe: "arjun's AI rep · knows his work" },
};

const INK = '#121212';

function manePoints(cx: number, cy: number, rOut: number, rIn: number, n: number): string {
  const points: string[] = [];
  for (let i = 0; i < n * 2; i++) {
    const angle = (i / (n * 2)) * Math.PI * 2 - Math.PI / 2;
    const r = i % 2 ? rIn : rOut + (i % 4 === 0 ? 7 : 0);
    points.push(`${(cx + Math.cos(angle) * r * 1.04).toFixed(1)},${(cy + Math.sin(angle) * r).toFixed(1)}`);
  }
  return points.join(' ');
}

const EARS = `<g class="ears" fill="none" stroke="${INK}" stroke-width="5" stroke-linecap="round" opacity="0"><path class="ear-l" d="M30 130 q-14 26 0 52"/><path class="ear-l" d="M14 118 q-22 38 0 76"/><path class="ear-r" d="M270 130 q14 26 0 52"/><path class="ear-r" d="M286 118 q22 38 0 76"/></g>`;
const THINK = `<g class="think" opacity="0" fill="#fff" stroke="${INK}" stroke-width="4"><circle cx="238" cy="38" r="7"/><circle cx="256" cy="18" r="10"/><circle cx="280" cy="-4" r="13"/></g>`;
const SHADOW = `<ellipse cx="150" cy="285" rx="90" ry="9" fill="${INK}" opacity=".12"/>`;

const openMouth = (cy: number, tongue: string): string =>
  `<g class="open" opacity="0"><ellipse class="mo" cx="150" cy="${cy}" rx="18" ry="4" fill="${INK}"/>${tongue}</g>`;

const limb = (d: string, colour: string, width = 10): string =>
  `<path d="${d}" fill="none" stroke="${INK}" stroke-width="${width + 8}" stroke-linecap="round"/><path d="${d}" fill="none" stroke="${colour}" stroke-width="${width}" stroke-linecap="round"/>`;

function sapwa(uid: string): string {
  const G = '#9ccc4a', GD = '#6f9f33', BELLY = '#e6ea9c';
  return `<defs><clipPath id="${uid}L"><ellipse cx="120" cy="104" rx="20" ry="22"/></clipPath><clipPath id="${uid}R"><ellipse cx="180" cy="104" rx="20" ry="22"/></clipPath></defs>
  ${EARS}${SHADOW}
  <g class="body">
    ${limb('M86 254 C40 258 32 214 64 206 C90 200 100 226 82 236', G, 12)}
    <path d="M56 284 C58 250 242 250 244 284 Z" fill="${G}" stroke="${INK}" stroke-width="6" stroke-linejoin="round"/>
    <path d="M120 270 q30 -10 60 0" fill="none" stroke="${GD}" stroke-width="3" stroke-linecap="round"/>
    ${limb('M104 208 q-30 6 -42 -16', G)}
    <line x1="236" y1="188" x2="286" y2="102" stroke="${INK}" stroke-width="10" stroke-linecap="round"/>
    <line x1="236" y1="188" x2="286" y2="102" stroke="#b47b42" stroke-width="5" stroke-linecap="round"/>
    ${limb('M196 208 q30 -2 42 -22', G)}
    <path d="M110 176 H190 L204 266 H96 Z" fill="#fff" stroke="${INK}" stroke-width="5" stroke-linejoin="round"/>
    <path d="M110 176 L138 176 L146 266 H96 Z" fill="#3d4b66" stroke="${INK}" stroke-width="5" stroke-linejoin="round"/>
    <path d="M190 176 L162 176 L154 266 H204 Z" fill="#3d4b66" stroke="${INK}" stroke-width="5" stroke-linejoin="round"/>
    <path d="M106 262 L140 262 M160 262 L200 262" stroke="#b47b42" stroke-width="4"/>
    <g fill="#c98d4a" stroke="${INK}" stroke-width="2"><circle cx="160" cy="214" r="4"/><circle cx="161" cy="238" r="4"/></g>
    <rect x="112" y="204" width="13" height="9" rx="2" fill="#f0c84a" stroke="${INK}" stroke-width="2"/>
    <path d="M124 150 C126 172 134 188 150 192 C166 188 174 172 176 150 Z" fill="${BELLY}" stroke="${INK}" stroke-width="5" stroke-linejoin="round"/>
    <path d="M133 166 h34 M138 179 h24" stroke="${GD}" stroke-width="3" stroke-linecap="round"/>
    <path d="M126 176 L140 194 M174 176 L160 194" stroke="${INK}" stroke-width="4" stroke-linecap="round"/>
    <ellipse cx="150" cy="108" rx="88" ry="64" fill="${G}" stroke="${INK}" stroke-width="6"/>
    <ellipse cx="150" cy="142" rx="62" ry="24" fill="#b8de70"/>
    <g fill="${INK}"><circle cx="140" cy="128" r="3"/><circle cx="160" cy="128" r="3"/></g>
    <g fill="#fff" stroke="${INK}" stroke-width="4"><ellipse cx="120" cy="104" rx="20" ry="22"/><ellipse cx="180" cy="104" rx="20" ry="22"/></g>
    <g class="pupils" fill="${INK}"><circle cx="123" cy="108" r="9"/><circle cx="177" cy="108" r="9"/></g>
    <g class="lids" fill="${G}"><rect clip-path="url(#${uid}L)" x="98" y="80" width="44" height="0"/><rect clip-path="url(#${uid}R)" x="158" y="80" width="44" height="0"/></g>
    <g fill="none" stroke="${INK}" stroke-width="5" stroke-linecap="round"><circle cx="120" cy="104" r="27"/><circle cx="180" cy="104" r="27"/><path d="M146 98 q4 -5 8 0"/><path d="M93 98 L64 90"/><path d="M207 98 L236 90"/></g>
    <g fill="none" stroke="${INK}" stroke-width="7" stroke-linecap="round"><path d="M96 58 q24 -16 46 -4"/><path d="M158 54 q24 -12 46 4"/></g>
    <g class="smile"><path d="M112 150 q38 28 76 0" fill="none" stroke="${INK}" stroke-width="5" stroke-linecap="round"/><g fill="#fff" stroke="${INK}" stroke-width="2"><rect x="140" y="160" width="9" height="10" rx="1.5"/><rect x="151" y="160" width="9" height="10" rx="1.5"/></g></g>
    ${openMouth(162, `<path class="tongue" d="M150 166 v14 m0 0 l-6 7 m6 -7 l6 7" fill="none" stroke="#ff4f7a" stroke-width="3.5" stroke-linecap="round"/>`)}
  </g>${THINK}`;
}

function sheru(): string {
  const MO = '#c4842f', MI = '#e3b05a', FACE = '#efcf92';
  return `${EARS}${SHADOW}
  <g class="body">
    <path d="M62 284 C64 222 98 194 150 194 C202 194 236 222 238 284 Z" fill="#f7f5ef" stroke="${INK}" stroke-width="6" stroke-linejoin="round"/>
    <path d="M124 206 L150 270 L176 206 Z" fill="#fff" stroke="${INK}" stroke-width="3.5" stroke-linejoin="round"/>
    <path d="M124 206 L104 246 L142 262" fill="none" stroke="${INK}" stroke-width="4" stroke-linejoin="round"/>
    <path d="M176 206 L196 246 L158 262" fill="none" stroke="${INK}" stroke-width="4" stroke-linejoin="round"/>
    <path d="M80 250 q14 -6 22 4" fill="none" stroke="#d8d4c8" stroke-width="3" stroke-linecap="round"/>
    <path d="M126 226 Q150 262 174 226" fill="none" stroke="${INK}" stroke-width="9" stroke-linecap="round" stroke-dasharray="0.1 9"/>
    <path d="M126 226 Q150 262 174 226" fill="none" stroke="#f0c040" stroke-width="6" stroke-linecap="round" stroke-dasharray="0.1 9"/>
    <g fill="#e9e6dd" stroke="${INK}" stroke-width="2"><circle cx="150" cy="276" r="3.5"/></g>
    <polygon points="${manePoints(150, 110, 108, 90, 15)}" fill="${MO}" stroke="${INK}" stroke-width="6" stroke-linejoin="round"/>
    <polygon points="${manePoints(150, 114, 92, 78, 13)}" fill="${MI}"/>
    <g stroke="${INK}" stroke-width="5"><circle cx="98" cy="56" r="15" fill="${MO}"/><circle cx="202" cy="56" r="15" fill="${MO}"/></g>
    <g fill="#f3d9a8"><circle cx="98" cy="56" r="7"/><circle cx="202" cy="56" r="7"/></g>
    <ellipse cx="150" cy="126" rx="62" ry="70" fill="${FACE}" stroke="${INK}" stroke-width="5"/>
    <path d="M150 62 v26" stroke="#dcb06a" stroke-width="12" stroke-linecap="round"/>
    <ellipse cx="150" cy="168" rx="42" ry="28" fill="#f8ebcf"/>
    <g fill="${INK}" opacity=".7"><circle cx="128" cy="166" r="2"/><circle cx="134" cy="174" r="2"/><circle cx="172" cy="166" r="2"/><circle cx="166" cy="174" r="2"/></g>
    <path d="M136 146 h28 l-14 14 z" fill="#3a2a22" stroke="${INK}" stroke-width="3" stroke-linejoin="round"/>
    <g class="smile"><path d="M150 160 v8 M150 168 q-11 10 -22 2 M150 168 q11 10 22 2" fill="none" stroke="${INK}" stroke-width="4" stroke-linecap="round"/></g>
    ${openMouth(176, `<ellipse class="tongue" cx="150" cy="184" rx="9" ry="3" fill="#ff6f9a"/>`)}
    <path d="M98 100 H202" stroke="#d4a73a" stroke-width="5" stroke-linecap="round"/>
    <path d="M96 102 h46 c2 24 -8 36 -24 36 c-16 0 -24 -14 -22 -36 z" fill="#1c1c22" stroke="#d4a73a" stroke-width="4" stroke-linejoin="round"/>
    <path d="M158 102 h46 c2 22 -6 36 -22 36 c-16 0 -26 -12 -24 -36 z" fill="#1c1c22" stroke="#d4a73a" stroke-width="4" stroke-linejoin="round"/>
    <g class="pupils" fill="#fff" opacity=".6"><ellipse cx="112" cy="114" rx="8" ry="3.5" transform="rotate(-25 112 114)"/><ellipse cx="174" cy="114" rx="8" ry="3.5" transform="rotate(-25 174 114)"/></g>
    <g class="lids"></g>
    <g stroke="${INK}" stroke-width="6" stroke-linecap="round"><path d="M100 84 l34 9"/><path d="M200 84 l-34 9"/></g>
  </g>${THINK}`;
}

function rep(uid: string): string {
  return `<defs><clipPath id="${uid}L"><ellipse cx="118" cy="138" rx="19" ry="22"/></clipPath><clipPath id="${uid}R"><ellipse cx="182" cy="138" rx="19" ry="22"/></clipPath></defs>
  ${EARS}${SHADOW}
  <g class="body">
    <circle cx="150" cy="156" r="106" fill="#7fd4ff" stroke="${INK}" stroke-width="6"/>
    <ellipse cx="96" cy="182" rx="14" ry="8" fill="#ff8fc8" opacity=".6"/><ellipse cx="204" cy="182" rx="14" ry="8" fill="#ff8fc8" opacity=".6"/>
    <g fill="#fff" stroke="${INK}" stroke-width="5"><ellipse cx="118" cy="138" rx="19" ry="22"/><ellipse cx="182" cy="138" rx="19" ry="22"/></g>
    <g class="pupils" fill="${INK}"><circle cx="118" cy="141" r="8.5"/><circle cx="182" cy="141" r="8.5"/></g>
    <g class="lids" fill="#7fd4ff"><rect clip-path="url(#${uid}L)" x="96" y="112" width="44" height="0"/><rect clip-path="url(#${uid}R)" x="160" y="112" width="44" height="0"/></g>
    <g fill="none" stroke="${INK}" stroke-width="5"><circle cx="118" cy="138" r="24"/><circle cx="182" cy="138" r="24"/><path d="M142 138 h16"/></g>
    <g class="smile"><path d="M132 196 q18 14 36 0" fill="none" stroke="${INK}" stroke-width="6" stroke-linecap="round"/></g>
    ${openMouth(200, `<ellipse class="tongue" cx="150" cy="208" rx="9" ry="3" fill="#ff6f9a"/>`)}
  </g>${THINK}`;
}

/** The SVG inner markup of a character. uid keeps clip-path ids unique when several are on one page. */
export function characterSvg(key: CharacterKey, uid: string): string {
  if (key === 'sapwa') return sapwa(uid);
  if (key === 'sheru') return sheru();
  return rep(uid);
}
