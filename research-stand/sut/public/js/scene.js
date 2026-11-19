import * as THREE from "../vendor/three.module.min.js";
import { mulberry32 } from "./rng.js";

const WIDTH = 960;
const HEIGHT = 540;
const PALETTE = [0x66ccff, 0xffcc66, 0x99ff99];

function makeNodes(count, seed) {
  const rand = mulberry32(seed);
  const nodes = [];
  for (let i = 0; i < count; i += 1) {
    nodes.push({
      x: (rand() - 0.5) * 34,
      y: (rand() - 0.5) * 16,
      z: (rand() - 0.5) * 20,
      rx: rand() * Math.PI,
      ry: rand() * Math.PI,
      speed: 0.2 + rand() * 0.8,
      color: Math.floor(rand() * PALETTE.length),
    });
  }
  return nodes;
}

function buildMaterials() {
  return PALETTE.map(
    (color) =>
      new THREE.MeshStandardMaterial({
        color,
        roughness: 0.65,
        metalness: 0.15,
      }),
  );
}

export function createScene({ canvas, render, objects, seed }) {
  const renderer = new THREE.WebGLRenderer({
    canvas,
    antialias: false,
    alpha: false,
    powerPreference: "high-performance",
  });
  renderer.setPixelRatio(1);
  renderer.setSize(WIDTH, HEIGHT, false);

  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x05080f);

  const camera = new THREE.PerspectiveCamera(55, WIDTH / HEIGHT, 0.1, 200);
  camera.position.set(0, 0, 26);

  scene.add(new THREE.HemisphereLight(0xffffff, 0x223344, 1.1));
  const sun = new THREE.DirectionalLight(0xffffff, 1.4);
  sun.position.set(6, 9, 7);
  scene.add(sun);

  const nodes = makeNodes(objects, seed);
  const materials = buildMaterials();
  const highDetail = new THREE.IcosahedronGeometry(0.42, 2);
  const lowDetail = new THREE.IcosahedronGeometry(0.42, 0);
  const dummy = new THREE.Object3D();

  const orbit = (t) => {
    camera.position.x = Math.sin(t * 0.0004) * 6;
    camera.position.y = Math.cos(t * 0.0003) * 2.5;
    camera.lookAt(0, 0, 0);
  };

  let update;

  if (render === "none") {
    update = () => {};
  } else if (render === "instanced") {
    const mesh = new THREE.InstancedMesh(highDetail, materials[0].clone(), nodes.length);
    const color = new THREE.Color();
    nodes.forEach((n, i) => {
      mesh.setColorAt(i, color.setHex(PALETTE[n.color]));
      dummy.position.set(n.x, n.y, n.z);
      dummy.rotation.set(n.rx, n.ry, 0);
      dummy.updateMatrix();
      mesh.setMatrixAt(i, dummy.matrix);
    });
    mesh.instanceColor.needsUpdate = true;
    mesh.instanceMatrix.needsUpdate = true;
    mesh.frustumCulled = false;
    scene.add(mesh);

    update = (t) => orbit(t);
  } else if (render === "lod") {
    const meshes = nodes.map((n) => {
      const mesh = new THREE.Mesh(highDetail, materials[n.color]);
      mesh.position.set(n.x, n.y, n.z);
      mesh.rotation.set(n.rx, n.ry, 0);
      mesh.frustumCulled = false;
      mesh.userData.level = 2;
      scene.add(mesh);
      return mesh;
    });

    let tick = 0;
    update = (t) => {
      orbit(t);
      tick += 1;
      if (tick % 60 !== 0) return;
      for (let i = 0; i < meshes.length; i += 1) {
        const mesh = meshes[i];
        const level = mesh.position.distanceTo(camera.position) < 22 ? 2 : 0;
        if (mesh.userData.level === level) continue;
        mesh.geometry = level === 2 ? highDetail : lowDetail;
        mesh.userData.level = level;
      }
    };
  } else {
    const meshes = nodes.map((n) => {
      const mesh = new THREE.Mesh(highDetail, materials[n.color]);
      mesh.position.set(n.x, n.y, n.z);
      mesh.rotation.set(n.rx, n.ry, 0);
      mesh.frustumCulled = false;
      scene.add(mesh);
      return mesh;
    });
    void meshes;

    update = (t) => orbit(t);
  }

  function gpuInfo() {
    const gl = renderer.getContext();
    const ext = gl.getExtension("WEBGL_debug_renderer_info");
    return {
      vendor: ext ? gl.getParameter(ext.UNMASKED_VENDOR_WEBGL) : "unknown",
      renderer: ext ? gl.getParameter(ext.UNMASKED_RENDERER_WEBGL) : "unknown",
      version: gl.getParameter(gl.VERSION),
    };
  }

  return {
    renderer,
    scene,
    camera,
    nodes: nodes.length,
    render,
    update,
    drawCalls: () => renderer.info.render.calls,
    triangles: () => renderer.info.render.triangles,
    gpuInfo,
  };
}
