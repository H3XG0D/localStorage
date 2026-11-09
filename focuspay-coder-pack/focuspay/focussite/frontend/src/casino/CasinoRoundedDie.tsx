import { useEffect, useRef, useState } from "react";

const GRID = [-1, -0.94, -0.88, -0.8, -0.72, 0, 0.72, 0.8, 0.88, 0.94, 1];
const FACES = [
  { axis: 2, sign: 1, value: 1 },
  { axis: 0, sign: 1, value: 2 },
  { axis: 1, sign: -1, value: 3 },
  { axis: 1, sign: 1, value: 4 },
  { axis: 0, sign: -1, value: 5 },
  { axis: 2, sign: -1, value: 6 },
];

function createRoundedDieGeometry(): Float32Array {
  const vertices: number[] = [];
  for (const { axis, sign, value } of FACES) {
    const axes = [0, 1, 2].filter((item) => item !== axis);
    const vertex = (u: number, v: number) => {
      const point = [0, 0, 0];
      point[axis] = sign;
      point[axes[0]] = u;
      point[axes[1]] = v;
      const center = point.map((n) => Math.max(-0.72, Math.min(0.72, n)));
      const delta = point.map((n, index) => n - center[index]);
      const length = Math.hypot(...delta) || 1;
      const normal = delta.map((n) => n / length);
      return [...center.map((n, index) => n + 0.28 * normal[index]), ...normal, u, v, value];
    };
    for (let row = 0; row < GRID.length - 1; row += 1) {
      for (let col = 0; col < GRID.length - 1; col += 1) {
        const a = vertex(GRID[col], GRID[row]);
        const b = vertex(GRID[col + 1], GRID[row]);
        const c = vertex(GRID[col + 1], GRID[row + 1]);
        const d = vertex(GRID[col], GRID[row + 1]);
        vertices.push(...a, ...b, ...c, ...a, ...c, ...d);
      }
    }
  }
  return new Float32Array(vertices);
}

const GEOMETRY = createRoundedDieGeometry();

const VERTEX_SHADER = `
attribute vec3 position;
attribute vec3 normal;
attribute vec2 uv;
attribute float face;
uniform vec2 angles;
varying vec3 vNormal;
varying vec2 vUv;
varying float vFace;
vec3 rotate(vec3 p) {
  float cx = cos(angles.x), sx = sin(angles.x);
  float cy = cos(angles.y), sy = sin(angles.y);
  p = vec3(cy*p.x + sy*p.z, p.y, -sy*p.x + cy*p.z);
  return vec3(p.x, cx*p.y - sx*p.z, sx*p.y + cx*p.z);
}
void main() {
  vec3 p = rotate(position);
  gl_Position = vec4(p.x / 2.0, -p.y / 2.0, -p.z / 4.0, 1.0);
  vNormal = rotate(normal);
  vUv = uv;
  vFace = face;
}`;

const FRAGMENT_SHADER = `
precision mediump float;
varying vec3 vNormal;
varying vec2 vUv;
varying float vFace;
float dotAt(vec2 center) {
  return 1.0 - smoothstep(.122, .143, distance(vUv, center));
}
void main() {
  float pip = 0.0;
  if (vFace < 1.5 || (vFace > 2.5 && vFace < 3.5) || (vFace > 4.5 && vFace < 5.5))
    pip += dotAt(vec2(0.0));
  if (vFace > 1.5) {
    pip += dotAt(vec2(-.42, -.42)) + dotAt(vec2(.42, .42));
  }
  if (vFace > 3.5) {
    pip += dotAt(vec2(-.42, .42)) + dotAt(vec2(.42, -.42));
  }
  if (vFace > 5.5) {
    pip += dotAt(vec2(-.42, 0.0)) + dotAt(vec2(.42, 0.0));
  }
  vec3 n = normalize(vNormal);
  float light = .68 + .30 * max(dot(n, normalize(vec3(-.4, -.6, 1.0))), 0.0);
  vec3 ivory = vec3(.98, .98, .97) * light;
  vec3 ink = vec3(.075) + .06 * light;
  gl_FragColor = vec4(mix(ivory, ink, min(pip, 1.0)), 1.0);
}`;

type DieRenderer = {
  draw: (rotation: { rx: number; ry: number }) => void;
  dispose: () => void;
};

function createRenderer(canvas: HTMLCanvasElement): DieRenderer | null {
  const gl = canvas.getContext("webgl", { alpha: true, antialias: true, depth: true });
  if (!gl) return null;
  const shaders: WebGLShader[] = [];
  const program = gl.createProgram();
  const buffer = gl.createBuffer();
  const dispose = () => {
    gl.deleteBuffer(buffer);
    if (program) gl.deleteProgram(program);
    shaders.forEach((shader) => gl.deleteShader(shader));
  };
  if (!program || !buffer) {
    dispose();
    return null;
  }
  try {
    for (const [type, source] of [
      [gl.VERTEX_SHADER, VERTEX_SHADER],
      [gl.FRAGMENT_SHADER, FRAGMENT_SHADER],
    ] as const) {
      const shader = gl.createShader(type);
      if (!shader) throw new Error("Die shader missing");
      shaders.push(shader);
      gl.shaderSource(shader, source);
      gl.compileShader(shader);
      if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) throw new Error("Die shader compilation failed");
      gl.attachShader(program, shader);
    }
    gl.linkProgram(program);
    if (!gl.getProgramParameter(program, gl.LINK_STATUS)) throw new Error("Die shader linking failed");
    gl.useProgram(program);
    gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
    gl.bufferData(gl.ARRAY_BUFFER, GEOMETRY, gl.STATIC_DRAW);
    for (const [name, size, offset] of [
      ["position", 3, 0],
      ["normal", 3, 3],
      ["uv", 2, 6],
      ["face", 1, 8],
    ] as const) {
      const location = gl.getAttribLocation(program, name);
      if (location < 0) continue;
      gl.enableVertexAttribArray(location);
      gl.vertexAttribPointer(location, size, gl.FLOAT, false, 36, offset * 4);
    }
    const angles = gl.getUniformLocation(program, "angles");
    const resolution = Math.round(192 * Math.min(window.devicePixelRatio || 1, 2));
    canvas.width = resolution;
    canvas.height = resolution;
    gl.viewport(0, 0, resolution, resolution);
    gl.enable(gl.DEPTH_TEST);
    gl.clearColor(0, 0, 0, 0);
    return {
      draw({ rx, ry }) {
        gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
        gl.uniform2f(angles, ((rx % 360) * Math.PI) / 180, ((ry % 360) * Math.PI) / 180);
        gl.drawArrays(gl.TRIANGLES, 0, GEOMETRY.length / 9);
      },
      dispose,
    };
  } catch {
    dispose();
    return null;
  }
}

export function CasinoRoundedDie({
  rotation,
  duration,
  onUnavailable,
}: {
  rotation: { rx: number; ry: number };
  duration: number;
  onUnavailable?: () => void;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const rendererRef = useRef<DieRenderer | null>(null);
  const currentRef = useRef(rotation);
  const unavailableRef = useRef(onUnavailable);
  unavailableRef.current = onUnavailable;
  const [contextVersion, setContextVersion] = useState(0);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const renderer = createRenderer(canvas);
    rendererRef.current = renderer;
    if (!renderer) unavailableRef.current?.();
    renderer?.draw(currentRef.current);
    const lost = (event: Event) => {
      event.preventDefault();
      rendererRef.current = null;
      unavailableRef.current?.();
    };
    const restored = () => setContextVersion((version) => version + 1);
    canvas.addEventListener("webglcontextlost", lost);
    canvas.addEventListener("webglcontextrestored", restored);
    return () => {
      canvas.removeEventListener("webglcontextlost", lost);
      canvas.removeEventListener("webglcontextrestored", restored);
      rendererRef.current = null;
      renderer?.dispose();
    };
  }, [contextVersion]);

  useEffect(() => {
    const from = currentRef.current;
    const target = { rx: rotation.rx, ry: rotation.ry };
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduce || (from.rx === target.rx && from.ry === target.ry)) {
      currentRef.current = target;
      rendererRef.current?.draw(target);
      return;
    }
    let frame = 0;
    const start = performance.now();
    const tick = (now: number) => {
      const progress = Math.min(1, (now - start) / Math.max(1, duration));
      const eased = 1 - (1 - progress) ** 3;
      const current = {
        rx: from.rx + (target.rx - from.rx) * eased,
        ry: from.ry + (target.ry - from.ry) * eased,
      };
      currentRef.current = current;
      rendererRef.current?.draw(current);
      if (progress < 1) frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [rotation.rx, rotation.ry, duration, contextVersion]);

  return <canvas ref={canvasRef} className="casino-die-canvas" aria-hidden />;
}
