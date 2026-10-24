// The 3D views, tiers A and B (PRD 16.2): Babylon.js on WebGPU (tier A) or WebGL2 (tier B). Loaded on demand, so it
// never weighs on the first frame (PRD 16.7). The scene draws the pitch, the control field, the players and the ball;
// the overlay grammar is painted onto the grass from the same Canvas 2D renderer as the 2D view, the way broadcast
// virtual graphics are, and text stays in the DOM above. Tier A computes the control field per pixel on the GPU from
// the players' positions; tier B shows the 25 Hz field from the worker as a texture.
import { Constants } from '@babylonjs/core/Engines/constants';
import { Engine } from '@babylonjs/core/Engines/engine';
import type { AbstractEngine } from '@babylonjs/core/Engines/abstractEngine';
import { WebGPUEngine } from '@babylonjs/core/Engines/webgpuEngine';
import { Scene } from '@babylonjs/core/scene';
import { FreeCamera } from '@babylonjs/core/Cameras/freeCamera';
import { HemisphericLight } from '@babylonjs/core/Lights/hemisphericLight';
import { DirectionalLight } from '@babylonjs/core/Lights/directionalLight';
import { Color3, Color4 } from '@babylonjs/core/Maths/math.color';
import { Matrix, Vector2, Vector3, Vector4 } from '@babylonjs/core/Maths/math.vector';
import { Material } from '@babylonjs/core/Materials/material';
import { StandardMaterial } from '@babylonjs/core/Materials/standardMaterial';
import { ShaderMaterial } from '@babylonjs/core/Materials/shaderMaterial';
import { ShaderLanguage } from '@babylonjs/core/Materials/shaderLanguage';
import { DynamicTexture } from '@babylonjs/core/Materials/Textures/dynamicTexture';
import { RawTexture } from '@babylonjs/core/Materials/Textures/rawTexture';
import { Texture } from '@babylonjs/core/Materials/Textures/texture';
import { TransformNode } from '@babylonjs/core/Meshes/transformNode';
import type { Mesh } from '@babylonjs/core/Meshes/mesh';
import { CreateGround } from '@babylonjs/core/Meshes/Builders/groundBuilder';
import { CreateCapsule } from '@babylonjs/core/Meshes/Builders/capsuleBuilder';
import { CreateCylinder } from '@babylonjs/core/Meshes/Builders/cylinderBuilder';
import { CreateSphere } from '@babylonjs/core/Meshes/Builders/sphereBuilder';
import { CreateDisc } from '@babylonjs/core/Meshes/Builders/discBuilder';
import { CreatePlane } from '@babylonjs/core/Meshes/Builders/planeBuilder';
import { CreateBox } from '@babylonjs/core/Meshes/Builders/boxBuilder';
import { FIELD_GRID } from '../lib/field';
import { PLAYERS, type Team, type XY } from '../lib/match';

export type View3D = 'broadcast' | 'tactical' | 'player' | 'goal';
export type Tier3D = 'A' | 'B';

/** Colours from the theme's tokens, read by the stage and handed over whenever the theme changes. */
export interface Theme3D {
  pitch: string;
  stripe: string;
  edge: string;
  chalk: string;
  bg: string;
  surface: string;
  surface2: string;
  line: string;
  text: string;
  muted: string;
  kes: string;
  ash: string;
  onKes: string;
  onAsh: string;
  ball: string;
  ballEdge: string;
  contour: string;
  fieldMax: number;
  font: string;
}

/** Everything one frame shows, in metres. */
export interface Frame3D {
  /** Moment time in seconds. */
  t: number;
  /** Wall-clock milliseconds, for camera motion. */
  now: number;
  pos: Readonly<Record<string, XY>>;
  /** Tier A: where the players are in the world the field shows, if not where they're drawn (ghosts over the real play). */
  fieldPos?: Readonly<Record<string, XY>>;
  ball: readonly [number, number, number];
  /** Tier B: the control field from the worker, row by row from the far touchline. */
  field: ArrayLike<number> | null;
  /** 0–1: how strongly this mode shows the field. */
  strength: number;
  /** Contour levels: 25, 50 and 75% in Analyst, the 50% line elsewhere. */
  levels: readonly number[];
  /** Players drawn faded, in Player focus. */
  dim: ReadonlySet<string>;
  /** Pointed at or focused: drawn a little larger. */
  highlight: string | null;
  /** The player cam's subject. */
  follow: string;
  /** Counterfactual figures: where a player would have been. */
  ghosts: readonly { team: Team; at: XY }[];
  /** What the graphics on screen are about (rings, runners, pass targets): the broadcast camera keeps them in shot. */
  focus: readonly XY[];
  reduced: boolean;
}

export interface Scene3D {
  readonly tier: Tier3D;
  /** The ground overlays are drawn into this canvas in pitch units (10 per metre, 3 m margin), then `overlayChanged`. */
  readonly overlayCanvas: HTMLCanvasElement;
  overlayChanged(): void;
  setTheme(theme: Theme3D): void;
  setView(view: View3D): void;
  render(frame: Frame3D): void;
  /** Where a point (metres, z up) lands on the canvas, in CSS pixels; null when it's behind the camera. */
  project(x: number, y: number, z: number): XY | null;
  /** True while the camera is settling or the scene is still compiling, so the stage keeps drawing a paused picture. */
  moving(): boolean;
  /** True once every material has compiled and the scene draws completely. */
  ready(): boolean;
  /**
   * Draws the picture again and copies it into `target` at a box in its current units, in the same task, so the copy
   * never depends on what the drawing buffer keeps after it's shown (PRD 16.8 snapshots).
   */
  capture(target: CanvasRenderingContext2D, x: number, y: number, w: number, h: number): void;
  resize(): void;
  dispose(): void;
}

// World space: x along the pitch (centred), y up, z across it (far touchline positive). Babylon is left-handed, so a
// camera on the near side looking across sees Kestrel Bay attack left to right, as in the 2D view.
const W = (x: number, y: number, z = 0) => new Vector3(x - 52.5, z, y - 34);
/** Figures are drawn 10% larger than life, so they read at broadcast distance. */
const FIGURE_SCALE = 1.1;

function parseColour(css: string): [number, number, number, number] {
  const s = css.trim();
  if (s.startsWith('#')) {
    const h = s.length === 4 ? [...s.slice(1)].map((c) => c + c).join('') : s.slice(1, 7);
    return [parseInt(h.slice(0, 2), 16) / 255, parseInt(h.slice(2, 4), 16) / 255, parseInt(h.slice(4, 6), 16) / 255, 1];
  }
  const m = /rgba?\(([^)]+)\)/.exec(s);
  if (m) {
    const parts = m[1].split(/[\s,/]+/).filter(Boolean).map(Number);
    return [parts[0] / 255, parts[1] / 255, parts[2] / 255, parts.length > 3 ? parts[3] : 1];
  }
  return [1, 0, 1, 1];
}
const c3 = (css: string) => {
  const [r, g, b] = parseColour(css);
  return new Color3(r, g, b);
};

// The control field, drawn over the grass. Tier B samples the worker's field; both tiers trace the contours from the
// field's own gradient, so they're crisp at any distance (PRD 16.3: the field reads without colour).
const FIELD_GLSL_VERTEX = `
precision highp float;
attribute vec3 position;
uniform mat4 world;
uniform mat4 worldViewProjection;
varying vec2 vPitch;
void main(void) {
  vec4 w = world * vec4(position, 1.0);
  vPitch = vec2(w.x + 52.5, w.z + 34.0);
  gl_Position = worldViewProjection * vec4(position, 1.0);
}`;

// The grid is 2 m a cell: sampled bilinearly, its contours kink at every cell edge and read as steps. A cubic B-spline
// through four bilinear taps gives a surface smooth to its second derivative, so the lines curve as in the 2D view.
const FIELD_GLSL_FRAGMENT = `
precision highp float;
varying vec2 vPitch;
uniform sampler2D field;
uniform vec2 fieldSize;
uniform vec3 kes;
uniform vec3 ash;
uniform vec4 contour;
uniform vec4 levels;
uniform float strength;
uniform float maxAlpha;
vec4 bspline(float v) {
  vec4 n = vec4(1.0, 2.0, 3.0, 4.0) - v;
  vec4 s = n * n * n;
  float x = s.x;
  float y = s.y - 4.0 * s.x;
  float z = s.z - 4.0 * s.y + 6.0 * s.x;
  return vec4(x, y, z, 6.0 - x - y - z) / 6.0;
}
float smoothField(vec2 uv) {
  vec2 t = uv * fieldSize - 0.5;
  vec2 f = fract(t);
  t -= f;
  vec4 xc = bspline(f.x);
  vec4 yc = bspline(f.y);
  vec4 c = t.xxyy + vec2(-0.5, 1.5).xyxy;
  vec4 s = vec4(xc.xz + xc.yw, yc.xz + yc.yw);
  vec4 o = (c + vec4(xc.yw, yc.yw) / s) / fieldSize.xxyy;
  float s0 = texture2D(field, o.xz).r;
  float s1 = texture2D(field, o.yz).r;
  float s2 = texture2D(field, o.xw).r;
  float s3 = texture2D(field, o.yw).r;
  float sx = s.x / (s.x + s.y);
  float sy = s.z / (s.z + s.w);
  return mix(mix(s3, s2, sx), mix(s1, s0, sx), sy);
}
void main(void) {
  vec2 uv = vec2(vPitch.x / 105.0, (68.0 - vPitch.y) / 68.0);
  float p = smoothField(uv);
  float a = min(1.0, abs(p - 0.5) * 2.0 * strength) * maxAlpha;
  vec3 team = p >= 0.5 ? kes : ash;
  float fw = max(fwidth(p), 1e-4);
  float line = 0.0;
  for (int j = 0; j < 3; j++) {
    if (float(j) < levels.w) {
      float l = j == 0 ? levels.x : (j == 1 ? levels.y : levels.z);
      float weight = abs(l - 0.5) < 0.01 ? 0.8 : 0.55;
      line = max(line, (1.0 - smoothstep(0.6, 1.6, abs(p - l) / fw)) * weight);
    }
  }
  float ca = contour.a * line;
  float outA = ca + a * (1.0 - ca);
  vec3 rgb = (contour.rgb * ca + team * a * (1.0 - ca)) / max(outA, 1e-4);
  gl_FragColor = vec4(rgb, outA);
}`;

// Tier A: the same model as lib/field.ts, run per pixel on the GPU from the 22 positions (PRD 16.2), as a smooth
// display version: each team's arrival time is a soft minimum over its players, within a quarter of a second of the
// hard one, so the regions round off where two players' reach meets instead of meeting in sharp straight-edged points.
// Numbers on screen still come from the interpret service's values, never from this.
const FIELD_WGSL_VERTEX = `
attribute position : vec3<f32>;
uniform world : mat4x4<f32>;
uniform worldViewProjection : mat4x4<f32>;
varying vPitch : vec2<f32>;
@vertex
fn main(input : VertexInputs) -> FragmentInputs {
  let w = uniforms.world * vec4<f32>(vertexInputs.position, 1.0);
  vertexOutputs.vPitch = vec2<f32>(w.x + 52.5, w.z + 34.0);
  vertexOutputs.position = uniforms.worldViewProjection * vec4<f32>(vertexInputs.position, 1.0);
}`;

const FIELD_WGSL_FRAGMENT = `
varying vPitch : vec2<f32>;
uniform players : array<vec4<f32>, 22>;
uniform kes : vec3<f32>;
uniform ash : vec3<f32>;
uniform contour : vec4<f32>;
uniform levels : vec4<f32>;
uniform strength : f32;
uniform maxAlpha : f32;
@fragment
fn main(input : FragmentInputs) -> FragmentOutputs {
  let q = fragmentInputs.vPitch;
  let soft = 0.25;
  var mk : f32 = 1e9;
  var ma : f32 = 1e9;
  for (var i = 0; i < 22; i++) {
    let b = uniforms.players[i];
    let time = 0.7 + distance(b.xy, q) / 7.0;
    if (b.z > 0.5) { mk = min(mk, time); } else { ma = min(ma, time); }
  }
  // Soft minimum, taken relative to the hard one so the exponentials stay in range.
  var sk : f32 = 0.0;
  var sa : f32 = 0.0;
  for (var i = 0; i < 22; i++) {
    let b = uniforms.players[i];
    let time = 0.7 + distance(b.xy, q) / 7.0;
    if (b.z > 0.5) { sk += exp(-(time - mk) / soft); } else { sa += exp(-(time - ma) / soft); }
  }
  let tk = mk - soft * log(max(sk, 1.0));
  let ta = ma - soft * log(max(sa, 1.0));
  let p = 1.0 / (1.0 + exp(-(ta - tk) / 0.35));
  let a = min(1.0, abs(p - 0.5) * 2.0 * uniforms.strength) * uniforms.maxAlpha;
  let team = select(uniforms.ash, uniforms.kes, p >= 0.5);
  let fw = max(fwidth(p), 1e-4);
  var line : f32 = 0.0;
  for (var j = 0; j < 3; j++) {
    if (f32(j) < uniforms.levels.w) {
      let l = uniforms.levels[j];
      let weight = select(0.55, 0.8, abs(l - 0.5) < 0.01);
      line = max(line, (1.0 - smoothstep(0.6, 1.6, abs(p - l) / fw)) * weight);
    }
  }
  let ca = uniforms.contour.a * line;
  let outA = ca + a * (1.0 - ca);
  let rgb = (uniforms.contour.rgb * ca + team * a * (1.0 - ca)) / max(outA, 1e-4);
  fragmentOutputs.color = vec4<f32>(rgb, outA);
}`;

/** The pitch's markings, painted once per theme: 105 × 68 m inside a 125 × 88 m ground, 10 m of run-off each side. */
function paintPitch(ctx: CanvasRenderingContext2D, w: number, h: number, t: Theme3D) {
  const k = w / 125;
  const X = (x: number) => (x + 10) * k;
  const Y = (y: number) => (78 - y) * k;
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.fillStyle = t.edge;
  ctx.fillRect(0, 0, w, h);
  for (let i = 0; i < 12; i++) {
    ctx.fillStyle = i % 2 ? t.stripe : t.pitch;
    const x0 = -5.25 + i * 10.5;
    ctx.fillRect(X(Math.max(-2, x0)), Y(70), (Math.min(107, x0 + 10.5) - Math.max(-2, x0)) * k, 72 * k);
  }
  ctx.strokeStyle = t.chalk;
  ctx.fillStyle = t.chalk;
  ctx.lineWidth = 0.12 * k;
  const rect = (x: number, y: number, rw: number, rh: number) => ctx.strokeRect(X(x), Y(y + rh), rw * k, rh * k);
  rect(0, 0, 105, 68);
  ctx.beginPath();
  ctx.moveTo(X(52.5), Y(0));
  ctx.lineTo(X(52.5), Y(68));
  ctx.stroke();
  const circle = (x: number, y: number, r: number, a0 = 0, a1 = Math.PI * 2) => {
    ctx.beginPath();
    ctx.arc(X(x), Y(y), r * k, a0, a1);
    ctx.stroke();
  };
  const spot = (x: number, y: number) => {
    ctx.beginPath();
    ctx.arc(X(x), Y(y), 0.2 * k, 0, Math.PI * 2);
    ctx.fill();
  };
  circle(52.5, 34, 9.15);
  spot(52.5, 34);
  for (const left of [true, false]) {
    const gx = left ? 0 : 105;
    const dir = left ? 1 : -1;
    rect(left ? 0 : 105 - 16.5, 34 - 20.16, 16.5, 40.32);
    rect(left ? 0 : 105 - 5.5, 34 - 9.16, 5.5, 18.32);
    spot(gx + dir * 11, 34);
    // The arc of the penalty area: the part of the 9.15 m circle around the spot outside the box.
    const a = Math.acos(5.5 / 9.15);
    if (left) circle(11, 34, 9.15, -a, a);
    else circle(94, 34, 9.15, Math.PI - a, Math.PI + a);
    // Corner arcs.
    for (const cy of [0, 68]) circle(gx, cy, 1, 0, Math.PI * 2);
  }
}

/** A thin net: a grid on a transparent ground, for the goals. */
function netTexture(scene: Scene, colour: string): DynamicTexture {
  const tex = new DynamicTexture('net', { width: 128, height: 128 }, scene, true);
  const ctx = tex.getContext() as unknown as CanvasRenderingContext2D;
  ctx.clearRect(0, 0, 128, 128);
  ctx.strokeStyle = colour;
  ctx.globalAlpha = 0.55;
  ctx.lineWidth = 2;
  for (let i = 0; i <= 128; i += 16) {
    ctx.beginPath();
    ctx.moveTo(i, 0);
    ctx.lineTo(i, 128);
    ctx.moveTo(0, i);
    ctx.lineTo(128, i);
    ctx.stroke();
  }
  tex.hasAlpha = true;
  tex.update();
  tex.wrapU = Texture.WRAP_ADDRESSMODE;
  tex.wrapV = Texture.WRAP_ADDRESSMODE;
  return tex;
}

interface Figure {
  id: string;
  team: Team;
  root: TransformNode;
  body: TransformNode;
  hips: [TransformNode, TransformNode];
  shoulders: [TransformNode, TransformNode];
  meshes: Mesh[];
  shadow: Mesh;
  /** Smoothed heading, radians in pitch terms (0 faces +x). */
  heading: number;
  /** Stride phase, advanced by distance run. */
  phase: number;
  last: XY | null;
  /** Moment time of the last placement, for speed. */
  lastT: number;
  scale: number;
}

interface Rig {
  pos: Vector3;
  target: Vector3;
  fov: number;
}

/**
 * Builds the scene on a canvas. Tier A asks for WebGPU and falls back to WebGL2 (the handle says which it got);
 * tier B is WebGL2. Throws when neither is available, and the stage falls back to the 2D view.
 */
export async function createScene3D(canvas: HTMLCanvasElement, opts: { tier: Tier3D; dpr: number; onLost: () => void }): Promise<Scene3D> {
  let tier: Tier3D = opts.tier;
  let engine: AbstractEngine | null = null;
  if (tier === 'A') {
    try {
      if (!(await WebGPUEngine.IsSupportedAsync)) throw new Error('No WebGPU adapter');
      const gpu = new WebGPUEngine(canvas, { antialias: true, stencil: false, adaptToDeviceRatio: false });
      await gpu.initAsync();
      engine = gpu;
    } catch {
      tier = 'B';
    }
  }
  if (!engine) {
    const gl = new Engine(canvas, true, { stencil: false, powerPreference: 'high-performance', preserveDrawingBuffer: false, failIfMajorPerformanceCaveat: false }, false);
    if (gl.webGLVersion < 2) {
      gl.dispose();
      throw new Error('WebGL2 is not available');
    }
    engine = gl;
  }
  const eng = engine;
  eng.setHardwareScalingLevel(1 / opts.dpr);
  eng.onContextLostObservable.add(() => opts.onLost());

  const scene = new Scene(eng);
  scene.skipPointerMovePicking = true;
  scene.skipFrustumClipping = false;
  scene.blockMaterialDirtyMechanism = false;

  const camera = new FreeCamera('camera', new Vector3(0, 24, -70), scene);
  camera.minZ = 0.5;
  camera.maxZ = 600;
  camera.inputs.clear();
  const sky = new HemisphericLight('sky', new Vector3(0.25, 1, -0.35), scene);
  sky.intensity = 0.9;
  const sun = new DirectionalLight('sun', new Vector3(-0.45, -1, 0.55), scene);
  sun.intensity = 0.5;

  // The grass and its markings: unlit, so the theme's pitch colours show exactly.
  const texW = tier === 'A' ? 4096 : 2048;
  const pitchTex = new DynamicTexture('pitch', { width: texW, height: Math.round((texW * 88) / 125) }, scene, true, Texture.TRILINEAR_SAMPLINGMODE);
  pitchTex.anisotropicFilteringLevel = tier === 'A' ? 16 : 8;
  const ground = CreateGround('ground', { width: 125, height: 88 }, scene);
  ground.position = W(52.5, 34, 0);
  const groundMat = new StandardMaterial('ground', scene);
  groundMat.disableLighting = true;
  groundMat.emissiveTexture = pitchTex;
  groundMat.specularColor = Color3.Black();
  ground.material = groundMat;

  // The control field, just above the grass.
  const fieldPlane = CreateGround('field', { width: 105, height: 68 }, scene);
  fieldPlane.position = W(52.5, 34, 0.012);
  const fieldData = new Uint8Array(FIELD_GRID.cols * FIELD_GRID.rows);
  let fieldTex: RawTexture | null = null;
  const fieldMat =
    tier === 'A'
      ? new ShaderMaterial(
          'field',
          scene,
          { vertexSource: FIELD_WGSL_VERTEX, fragmentSource: FIELD_WGSL_FRAGMENT },
          { attributes: ['position'], uniforms: ['world', 'worldViewProjection', 'players', 'kes', 'ash', 'contour', 'levels', 'strength', 'maxAlpha'], needAlphaBlending: true, shaderLanguage: ShaderLanguage.WGSL },
        )
      : new ShaderMaterial(
          'field',
          scene,
          { vertexSource: FIELD_GLSL_VERTEX, fragmentSource: FIELD_GLSL_FRAGMENT },
          { attributes: ['position'], uniforms: ['world', 'worldViewProjection', 'fieldSize', 'kes', 'ash', 'contour', 'levels', 'strength', 'maxAlpha'], samplers: ['field'], needAlphaBlending: true },
        );
  if (tier === 'B') {
    fieldTex = RawTexture.CreateRTexture(fieldData, FIELD_GRID.cols, FIELD_GRID.rows, scene, false, false, Texture.BILINEAR_SAMPLINGMODE, Constants.TEXTURETYPE_UNSIGNED_BYTE);
    fieldTex.wrapU = Texture.CLAMP_ADDRESSMODE;
    fieldTex.wrapV = Texture.CLAMP_ADDRESSMODE;
    fieldMat.setTexture('field', fieldTex);
    fieldMat.setVector2('fieldSize', new Vector2(FIELD_GRID.cols, FIELD_GRID.rows));
  }
  fieldMat.backFaceCulling = false;
  fieldMat.disableDepthWrite = true;
  fieldPlane.material = fieldMat;
  const playerData = new Array<number>(PLAYERS.length * 4).fill(0);

  // The ground overlays, painted by the 2D renderer: rings, runs, passes, ghosts' footprints, the back line.
  const overlayCanvas = document.createElement('canvas');
  overlayCanvas.width = tier === 'A' ? 2220 : 1665;
  overlayCanvas.height = Math.round((overlayCanvas.width * 740) / 1110);
  const overlayTex = new DynamicTexture('overlays', overlayCanvas, scene, true, Texture.TRILINEAR_SAMPLINGMODE);
  overlayTex.hasAlpha = true;
  overlayTex.anisotropicFilteringLevel = tier === 'A' ? 16 : 8;
  const overlayPlane = CreateGround('overlays', { width: 111, height: 74 }, scene);
  overlayPlane.position = W(52.5, 34, 0.024);
  const overlayMat = new StandardMaterial('overlays', scene);
  overlayMat.disableLighting = true;
  overlayMat.emissiveTexture = overlayTex;
  overlayMat.opacityTexture = overlayTex;
  overlayMat.specularColor = Color3.Black();
  overlayMat.backFaceCulling = false;
  overlayMat.disableDepthWrite = true;
  overlayMat.transparencyMode = Material.MATERIAL_ALPHABLEND;
  overlayPlane.material = overlayMat;

  // Shared materials for the figures; colours set from the theme.
  const mat = (name: string) => {
    const m = new StandardMaterial(name, scene);
    m.specularColor = new Color3(0.08, 0.08, 0.08);
    return m;
  };
  const shirt: Record<Team, StandardMaterial> = { kes: mat('shirt-kes'), ash: mat('shirt-ash') };
  const shorts: Record<Team, StandardMaterial> = { kes: mat('shorts-kes'), ash: mat('shorts-ash') };
  const socks: Record<Team, StandardMaterial> = { kes: mat('socks-kes'), ash: mat('socks-ash') };
  // Heads are a neutral mannequin tone: the figures are stylised, not portraits.
  const headMat = mat('head');
  const shadowMat = new StandardMaterial('shadow', scene);
  shadowMat.disableLighting = true;
  shadowMat.emissiveColor = Color3.Black();
  shadowMat.alpha = 0.32;
  shadowMat.disableDepthWrite = true;
  const ghostMat: Record<Team, StandardMaterial> = { kes: mat('ghost-kes'), ash: mat('ghost-ash') };
  for (const g of Object.values(ghostMat)) {
    g.alpha = 0.28;
    g.disableDepthWrite = true;
  }

  // A shirt number on the back of each player.
  const numberTex = new Map<string, DynamicTexture>();
  const numberMats: StandardMaterial[] = [];
  const paintNumber = (tex: DynamicTexture, num: number, colour: string, font: string) => {
    const ctx = tex.getContext() as unknown as CanvasRenderingContext2D;
    ctx.clearRect(0, 0, 128, 128);
    ctx.fillStyle = colour;
    ctx.font = `700 92px ${font}`;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText(String(num), 64, 70);
    tex.update();
  };

  const figures: Figure[] = [];
  const makeFigure = (id: string, team: Team, num: number | null, ghost = false): Figure => {
    const root = new TransformNode(`${id}:root`, scene);
    const body = new TransformNode(`${id}:body`, scene);
    body.parent = root;
    const meshes: Mesh[] = [];
    const add = <M extends Mesh>(m: M, parent: TransformNode, material: StandardMaterial): M => {
      m.parent = parent;
      m.material = ghost ? ghostMat[team] : material;
      meshes.push(m);
      return m;
    };
    const torso = add(CreateCapsule(`${id}:torso`, { height: 0.66, radius: 0.19, tessellation: 12, capSubdivisions: 3 }, scene), body, shirt[team]);
    torso.position.y = 1.18;
    torso.scaling.z = 0.72;
    const pants = add(CreateCylinder(`${id}:shorts`, { height: 0.24, diameterTop: 0.37, diameterBottom: 0.42, tessellation: 12 }, scene), body, shorts[team]);
    pants.position.y = 0.86;
    pants.scaling.z = 0.75;
    const head = add(CreateSphere(`${id}:head`, { diameter: 0.25, segments: 10 }, scene), body, headMat);
    head.position.y = 1.67;
    const limb = (name: string, x: number, y: number, len: number, r: number, material: StandardMaterial) => {
      const pivot = new TransformNode(`${id}:${name}`, scene);
      pivot.parent = body;
      pivot.position.set(x, y, 0);
      const m = add(CreateCapsule(`${id}:${name}:mesh`, { height: len, radius: r, tessellation: 8, capSubdivisions: 2 }, scene), pivot, material);
      m.position.y = -len / 2 + r;
      return pivot;
    };
    const hips: [TransformNode, TransformNode] = [limb('hipL', -0.1, 0.84, 0.86, 0.075, socks[team]), limb('hipR', 0.1, 0.84, 0.86, 0.075, socks[team])];
    const shoulders: [TransformNode, TransformNode] = [limb('armL', -0.25, 1.43, 0.62, 0.055, shirt[team]), limb('armR', 0.25, 1.43, 0.62, 0.055, shirt[team])];
    if (num !== null && !ghost) {
      const plate = CreatePlane(`${id}:number`, { size: 0.26 }, scene);
      plate.parent = body;
      plate.position.set(0, 1.22, -0.15);
      const tex = new DynamicTexture(`${id}:number`, { width: 128, height: 128 }, scene, false);
      tex.hasAlpha = true;
      numberTex.set(id, tex);
      const m = new StandardMaterial(`${id}:number`, scene);
      m.disableLighting = true;
      m.emissiveTexture = tex;
      m.opacityTexture = tex;
      m.backFaceCulling = true;
      plate.material = m;
      numberMats.push(m);
      meshes.push(plate);
    }
    const shadow = CreateDisc(`${id}:shadow`, { radius: 0.5, tessellation: 20 }, scene);
    shadow.rotation.x = Math.PI / 2;
    shadow.material = shadowMat;
    shadow.position.y = 0.034;
    if (ghost) shadow.isVisible = false;
    return { id, team, root, body, hips, shoulders, meshes, shadow, heading: team === 'kes' ? 0 : Math.PI, phase: 0, last: null, lastT: 0, scale: FIGURE_SCALE };
  };
  for (const p of PLAYERS) figures.push(makeFigure(p.id, p.team, p.num));
  const ghostFigures: Record<Team, Figure> = { kes: makeFigure('ghost-kes', 'kes', null, true), ash: makeFigure('ghost-ash', 'ash', null, true) };

  // The ball, a little larger than life so it reads at broadcast distance, with its shadow.
  const ball = CreateSphere('ball', { diameter: 0.38, segments: 14 }, scene);
  const ballMat = new StandardMaterial('ball', scene);
  ballMat.specularColor = new Color3(0.4, 0.4, 0.4);
  ball.material = ballMat;
  const ballShadow = CreateDisc('ball-shadow', { radius: 0.3, tessellation: 16 }, scene);
  ballShadow.rotation.x = Math.PI / 2;
  ballShadow.material = shadowMat;

  // Goals: posts, crossbar and a net, at both ends.
  const postMat = new StandardMaterial('posts', scene);
  postMat.emissiveColor = new Color3(0.85, 0.85, 0.85);
  postMat.disableLighting = true;
  const netMat = new StandardMaterial('net', scene);
  netMat.disableLighting = true;
  netMat.backFaceCulling = false;
  netMat.disableDepthWrite = true;
  for (const gx of [0, 105]) {
    const out = gx === 0 ? -1 : 1;
    for (const py of [30.34, 37.66]) {
      const post = CreateCylinder('post', { height: 2.44, diameter: 0.12, tessellation: 10 }, scene);
      post.position = W(gx, py, 1.22);
      post.material = postMat;
    }
    const bar = CreateCylinder('bar', { height: 7.44, diameter: 0.12, tessellation: 10 }, scene);
    bar.rotation.x = Math.PI / 2;
    bar.position = W(gx, 34, 2.44);
    bar.material = postMat;
    const back = CreatePlane('net-back', { width: 7.32, height: 2.44 }, scene);
    back.position = W(gx + out * 2, 34, 1.22);
    back.rotation.y = Math.PI / 2;
    back.material = netMat;
    const roof = CreatePlane('net-roof', { width: 2, height: 7.32 }, scene);
    roof.position = W(gx + out, 34, 2.44);
    roof.rotation.x = Math.PI / 2;
    roof.material = netMat;
    for (const py of [30.34, 37.66]) {
      const side = CreatePlane('net-side', { width: 2, height: 2.44 }, scene);
      side.position = W(gx + out, py, 1.22);
      side.material = netMat;
    }
  }

  // Raked stands on three sides, with a crowd, and an advertising board along the far touchline: a sense of place.
  const standMat = new StandardMaterial('stands', scene);
  standMat.specularColor = Color3.Black();
  const crowdTex = new DynamicTexture('crowd', { width: 512, height: 512 }, scene, true, Texture.TRILINEAR_SAMPLINGMODE);
  crowdTex.wrapU = Texture.WRAP_ADDRESSMODE;
  crowdTex.wrapV = Texture.WRAP_ADDRESSMODE;
  standMat.diffuseTexture = crowdTex;
  const boardMat = new StandardMaterial('board', scene);
  boardMat.disableLighting = true;
  const boardTex = new DynamicTexture('board', { width: 2048, height: 64 }, scene, true);
  boardMat.emissiveTexture = boardTex;
  // A slope 26 m long, raked at 0.5 rad: its front edge meets the ground 8 m behind the line, its back is 12.6 m up.
  const RAKE = 0.5;
  const SLOPE = 26;
  const reach = (SLOPE / 2) * Math.cos(RAKE);
  const rise = (SLOPE / 2) * Math.sin(RAKE);
  const stand = (x: number, y: number, w: number, rotY: number) => {
    const st = CreateBox('stand', { width: w, height: 0.6, depth: SLOPE }, scene);
    st.position = W(x, y, rise + 0.2);
    st.rotation.y = rotY;
    // Negative pitch lifts the stand's far edge, away from the pitch.
    st.rotation.x = -RAKE;
    st.material = standMat;
    return st;
  };
  stand(52.5, 68 + 8 + reach, 150, 0);
  stand(-8 - reach, 34, 104, -Math.PI / 2);
  stand(105 + 8 + reach, 34, 104, Math.PI / 2);
  // One material for every stand: the crowd tiles every 8 m.
  crowdTex.uScale = 150 / 8;
  crowdTex.vScale = SLOPE / 8;
  const board = CreateBox('board', { width: 104, height: 0.9, depth: 0.12 }, scene);
  board.position = W(52.5, 68 + 4.5, 0.45);
  board.material = boardMat;

  let theme: Theme3D | null = null;
  const setTheme = (t: Theme3D) => {
    theme = t;
    scene.clearColor = Color4.FromColor3(c3(t.bg), 1);
    const ctx = pitchTex.getContext() as unknown as CanvasRenderingContext2D;
    const size = pitchTex.getSize();
    paintPitch(ctx, size.width, size.height, t);
    pitchTex.update();
    for (const team of ['kes', 'ash'] as const) {
      const colour = c3(team === 'kes' ? t.kes : t.ash);
      shirt[team].diffuseColor = colour;
      shirt[team].emissiveColor = colour.scale(0.18);
      shorts[team].diffuseColor = c3(team === 'kes' ? t.onKes : t.onAsh).scale(0.6).add(colour.scale(0.25));
      socks[team].diffuseColor = colour.scale(0.85);
      ghostMat[team].diffuseColor = colour;
      ghostMat[team].emissiveColor = colour.scale(0.5);
    }
    headMat.diffuseColor = c3(t.muted);
    ballMat.diffuseColor = c3(t.ball);
    ballMat.emissiveColor = c3(t.ball).scale(0.35);
    standMat.diffuseColor = Color3.White();
    standMat.emissiveColor = c3(t.surface).scale(0.35);
    // The crowd: seeded, so every picture of the same moment is the same, with fans in both teams' colours.
    const crowd = crowdTex.getContext() as unknown as CanvasRenderingContext2D;
    crowd.fillStyle = t.surface2;
    crowd.fillRect(0, 0, 512, 512);
    let seed = 7;
    const rand = () => ((seed = (seed * 16807) % 2147483647) - 1) / 2147483646;
    const tones = [t.muted, t.line, t.surface, t.text, t.kes, t.ash];
    for (let row = 0; row < 16; row++) {
      for (let col = 0; col < 24; col++) {
        const r = rand();
        crowd.fillStyle = tones[r < 0.12 ? 4 : r < 0.2 ? 5 : r < 0.35 ? 3 : Math.floor(rand() * 3)];
        crowd.globalAlpha = 0.35 + rand() * 0.35;
        crowd.beginPath();
        crowd.arc(col * 21.3 + 10 + (row % 2) * 10, row * 32 + 14, 6 + rand() * 2, 0, Math.PI * 2);
        crowd.fill();
      }
    }
    crowd.globalAlpha = 1;
    crowdTex.update();
    netMat.emissiveTexture?.dispose();
    const net = netTexture(scene, t.text);
    net.uScale = 6;
    net.vScale = 2;
    netMat.emissiveTexture = net;
    netMat.opacityTexture = net;
    const bctx = boardTex.getContext() as unknown as CanvasRenderingContext2D;
    bctx.fillStyle = t.surface;
    bctx.fillRect(0, 0, 2048, 64);
    bctx.fillStyle = t.muted;
    bctx.font = `700 34px ${t.font}`;
    bctx.textBaseline = 'middle';
    bctx.textAlign = 'center';
    const slogan = 'OffBall · space view · synthetic match';
    // Only whole slogans, spaced evenly along the board: none is ever cut off at its end.
    const copies = Math.max(1, Math.floor(2048 / (bctx.measureText(slogan).width + 80)));
    for (let i = 0; i < copies; i++) bctx.fillText(slogan, ((i + 0.5) * 2048) / copies, 34);
    boardTex.update();
    for (const p of PLAYERS) {
      const tex = numberTex.get(p.id);
      if (tex) paintNumber(tex, p.num, p.team === 'kes' ? t.onKes : t.onAsh, t.font);
    }
    const [kr, kg, kb] = parseColour(t.kes);
    const [ar, ag, ab] = parseColour(t.ash);
    const [cr, cg, cb, ca] = parseColour(t.contour);
    fieldMat.setColor3('kes', new Color3(kr, kg, kb));
    fieldMat.setColor3('ash', new Color3(ar, ag, ab));
    fieldMat.setColor4('contour', new Color4(cr, cg, cb, ca));
    fieldMat.setFloat('maxAlpha', t.fieldMax);
  };

  // Cameras: a rig per view, eased towards where the view wants to be (PRD 15.1).
  let view: View3D = 'broadcast';
  const rig: Rig = { pos: camera.position.clone(), target: W(70, 34, 0), fov: 0.55 };
  let settled = false;
  let ready = false;
  let lastNow = 0;
  let lastT = Number.NaN;
  let cutAt = -Infinity;

  const desired = (f: Frame3D): Rig => {
    const aspect = eng.getAspectRatio(camera) || 16 / 9;
    const bx = f.ball[0];
    const by = f.ball[1];
    // The story in shot: the ball, the three players nearest it, and whatever the graphics are about.
    const near = PLAYERS.map((p) => f.pos[p.id])
      .filter(Boolean)
      .map((p) => ({ p, d: Math.hypot(p[0] - bx, p[1] - by) }))
      .sort((a, b) => a.d - b.d)
      .slice(0, 3)
      .map((n) => n.p);
    const pts: XY[] = [[bx, by], ...near, ...f.focus];
    const xs = pts.map((p) => p[0]);
    const ys = pts.map((p) => p[1]);
    const minX = Math.min(...xs);
    const maxX = Math.max(...xs);
    const minY = Math.min(...ys);
    const maxY = Math.max(...ys);
    const cx = (minX + maxX) / 2;
    const cy = (minY + maxY) / 2;
    // Half the width to keep in shot: across the pitch it's the x extent; depth needs a little more room too.
    const spread = Math.max(11, Math.min(40, Math.max((maxX - minX) / 2 + 7, (maxY - minY) * 0.55 + 5)));
    const fit = (pos: Vector3, target: Vector3, halfWidth: number, min: number, max: number) => {
      const dist = Vector3.Distance(pos, target);
      const hfov = 2 * Math.atan(halfWidth / dist);
      return Math.max(min, Math.min(max, 2 * Math.atan(Math.tan(hfov / 2) / aspect)));
    };
    switch (view) {
      case 'tactical': {
        const x = 52.5 + (cx - 52.5) * 0.3;
        const pos = W(x, -46, 60);
        const target = W(x, 31, 0);
        return { pos, target, fov: fit(pos, target, 62, 0.5, 1.1) };
      }
      case 'player': {
        const fig = figures.find((g) => g.id === f.follow);
        const at = fig && f.pos[fig.id];
        if (fig && at) {
          const dx = Math.cos(fig.heading);
          const dy = Math.sin(fig.heading);
          // Look past the player the way they're running, turned a little towards the ball.
          const lx = at[0] + dx * 12 * 0.8 + (bx - at[0]) * 0.2;
          const ly = at[1] + dy * 12 * 0.8 + (by - at[1]) * 0.2;
          return { pos: W(at[0] - dx * 7, at[1] - dy * 7, 3.2), target: W(lx, ly, 1), fov: 0.8 };
        }
        break;
      }
      case 'goal': {
        const pos = W(105 + 17, 34 + (by - 34) * 0.2, 7.5);
        const target = W(82, 34 + (by - 34) * 0.45, 0);
        return { pos, target, fov: 0.66 };
      }
    }
    // Broadcast: a gantry on the near side that pans with the play and zooms to fit it. A tall frame (a phone held
    // upright) looks down more steeply from closer in, so the pitch fills it rather than the sky.
    if (aspect < 1) {
      const pos = W(cx * 0.9 + 52.5 * 0.1, cy - 34, 36);
      const target = W(cx, cy + 3, 0);
      return { pos, target, fov: fit(pos, target, spread * 0.85, 0.3, 1.1) };
    }
    const pos = W(cx * 0.85 + 52.5 * 0.15, -36, 22);
    const target = W(cx, cy * 0.8 + 34 * 0.2, 0);
    return { pos, target, fov: fit(pos, target, spread, 0.2, 0.72) };
  };

  const moveCamera = (f: Frame3D) => {
    const want = desired(f);
    const dt = lastNow ? Math.min(0.1, Math.max(0, (f.now - lastNow) / 1000)) : 0;
    lastNow = f.now;
    // A jump in time (a scrub or a loop) cuts rather than glides.
    const jumped = !Number.isFinite(lastT) || Math.abs(f.t - lastT) > 0.5;
    lastT = f.t;
    const far = Vector3.Distance(rig.target, want.target);
    if (jumped || f.reduced) {
      // Reduced motion: no gliding (PRD 16.10). The camera holds still and cuts when the play moves on.
      if (jumped || far > 9 || (f.now - cutAt > 2000 && far > 3) || Math.abs(rig.fov - want.fov) > 0.15) {
        rig.pos.copyFrom(want.pos);
        rig.target.copyFrom(want.target);
        rig.fov = want.fov;
        cutAt = f.now;
      }
      settled = true;
    } else {
      const ease = (tau: number) => 1 - Math.exp(-dt / tau);
      rig.pos = Vector3.Lerp(rig.pos, want.pos, ease(0.65));
      rig.target = Vector3.Lerp(rig.target, want.target, ease(0.35));
      rig.fov += (want.fov - rig.fov) * ease(0.8);
      settled = Vector3.Distance(rig.pos, want.pos) < 0.05 && far < 0.05 && Math.abs(rig.fov - want.fov) < 0.002;
    }
    camera.position.copyFrom(rig.pos);
    camera.setTarget(rig.target);
    camera.fov = rig.fov;
  };

  const placeFigure = (g: Figure, at: XY | undefined, f: Frame3D, dim: boolean, highlight: boolean) => {
    if (!at) {
      g.root.setEnabled(false);
      g.shadow.isVisible = false;
      return;
    }
    g.root.setEnabled(true);
    const moved = g.last ? Math.hypot(at[0] - g.last[0], at[1] - g.last[1]) : 0;
    const dt = f.t - g.lastT;
    if (g.last && moved > 0.004) {
      const want = Math.atan2(at[1] - g.last[1], at[0] - g.last[0]);
      let d = want - g.heading;
      while (d > Math.PI) d -= Math.PI * 2;
      while (d < -Math.PI) d += Math.PI * 2;
      g.heading += d * Math.min(1, 0.25 + moved * 2);
    }
    g.last = [at[0], at[1]];
    g.lastT = f.t;
    g.root.position.set(at[0] - 52.5, 0, at[1] - 34);
    // Pitch heading 0 faces +x; Babylon's rotation.y turns +z towards +x.
    g.root.rotation.y = Math.PI / 2 - g.heading;
    // Animated from speed and heading, not poses (PRD 2: no pose estimation). A paused picture keeps its stride.
    if (dt !== 0) {
      // Strides follow the distance run, so scrubbing backwards and forwards stays in step.
      if (moved < 3) g.phase += (moved / 1.45) * Math.PI;
      const pace = Math.min(1, moved / Math.max(1e-3, Math.abs(dt)) / 7);
      const swing = Math.sin(g.phase) * 0.65 * pace;
      g.hips[0].rotation.x = swing;
      g.hips[1].rotation.x = -swing;
      g.shoulders[0].rotation.x = -swing * 0.7;
      g.shoulders[1].rotation.x = swing * 0.7;
      g.body.position.y = Math.abs(Math.sin(g.phase)) * 0.05 * pace;
      g.body.rotation.x = 0.12 * pace;
    }
    const scale = (highlight ? 1.12 : 1) * FIGURE_SCALE;
    g.scale += (scale - g.scale) * 0.35;
    g.root.scaling.setAll(g.scale);
    const visibility = dim ? 0.4 : 1;
    for (const m of g.meshes) m.visibility = visibility;
    g.shadow.isVisible = true;
    g.shadow.position.x = at[0] - 52.5 + 0.18;
    g.shadow.position.z = at[1] - 34 - 0.12;
    g.shadow.visibility = visibility;
  };

  const draw = () => {
    eng.beginFrame();
    scene.render();
    eng.endFrame();
  };

  const render = (f: Frame3D) => {
    if (!theme) return;
    // A large jump resets the strides' memory, so nobody spins round on a scrub.
    if (Number.isFinite(lastT) && Math.abs(f.t - lastT) > 0.5) for (const g of figures) g.last = null;
    for (const g of figures) placeFigure(g, f.pos[g.id], f, f.dim.has(g.id), f.highlight === g.id);
    for (const team of ['kes', 'ash'] as const) {
      const ghost = f.ghosts.find((gh) => gh.team === team);
      placeFigure(ghostFigures[team], ghost?.at, f, false, false);
      ghostFigures[team].shadow.isVisible = false;
    }
    const [bx, by, bz] = f.ball;
    ball.position = W(bx, by, bz + 0.19);
    ballShadow.position = W(bx + 0.1, by - 0.06, 0.036);
    ballShadow.visibility = Math.max(0.2, 1 - bz / 4);
    // The field: tier A from the positions, tier B from the worker's grid.
    if (tier === 'A') {
      const fieldPos = f.fieldPos ?? f.pos;
      PLAYERS.forEach((p, i) => {
        const at = fieldPos[p.id];
        playerData[i * 4] = at ? at[0] : -1000;
        playerData[i * 4 + 1] = at ? at[1] : -1000;
        playerData[i * 4 + 2] = p.team === 'kes' ? 1 : 0;
        playerData[i * 4 + 3] = 1;
      });
      fieldMat.setArray4('players', playerData);
    } else if (fieldTex && f.field) {
      for (let i = 0; i < fieldData.length; i++) fieldData[i] = Math.round(Math.max(0, Math.min(1, f.field[i])) * 255);
      fieldTex.update(fieldData);
    }
    const hasField = tier === 'A' || !!f.field;
    fieldMat.setFloat('strength', hasField ? f.strength : 0);
    fieldMat.setVector4('levels', new Vector4(f.levels[0] ?? 0.5, f.levels[1] ?? 0.5, f.levels[2] ?? 0.5, f.levels.length));
    moveCamera(f);
    draw();
    // Materials compile in the background; until they all have, a paused picture isn't finished.
    ready = scene.isReady(false);
  };

  const project = (x: number, y: number, z: number): XY | null => {
    const vp = camera.viewport.toGlobal(eng.getRenderWidth(), eng.getRenderHeight());
    const v = Vector3.Project(W(x, y, z), Matrix.IdentityReadOnly, scene.getTransformMatrix(), vp);
    if (v.z < 0 || v.z > 1) return null;
    const s = eng.getHardwareScalingLevel();
    return [v.x * s, v.y * s];
  };

  return {
    tier,
    overlayCanvas,
    overlayChanged: () => overlayTex.update(true),
    setTheme,
    setView: (v) => {
      view = v;
      lastT = Number.NaN;
    },
    render,
    project,
    moving: () => !settled || !ready,
    ready: () => ready,
    capture: (target, x, y, w, h) => {
      draw();
      target.drawImage(canvas, x, y, w, h);
    },
    resize: () => eng.resize(),
    dispose: () => {
      scene.dispose();
      eng.dispose();
    },
  };
}
