/**
 * Mini3d — 轻量 Three.js 3D 地图引擎
 * 从 ThreeMaps 项目提取并适配为纯 ES Module（无构建工具依赖）
 */

import * as THREE from 'three';
import { CSS3DRenderer, CSS3DObject, CSS3DSprite } from 'three/addons/renderers/CSS3DRenderer.js';

// ==================== EventEmitter ====================
class EventEmitter {
  constructor() {
    this.events = new Map();
  }
  on(event, callback) {
    let callbacks = this.events.get(event);
    if (!callbacks) { callbacks = new Set(); this.events.set(event, callbacks); }
    callbacks.add(callback);
  }
  off(event, callback) {
    const callbacks = this.events.get(event);
    if (callbacks) {
      if (callback) { callbacks.delete(callback); }
      else { this.events.delete(event); }
    }
  }
  emit(event, ...args) {
    const callbacks = this.events.get(event);
    if (callbacks) { callbacks.forEach(cb => cb(...args)); }
  }
  once(event, callback) {
    const onceWrapper = (...args) => { callback(...args); this.off(event, onceWrapper); };
    this.on(event, onceWrapper);
  }
}

// ==================== RafFn ====================
function RafFn(callback) {
  let rafId = null, isActive = false, paused = false;
  function animate() { if (!isActive || paused) return; callback(); rafId = requestAnimationFrame(animate); }
  function start() { if (!isActive) { isActive = true; animate(); } }
  function pause() { if (isActive) { isActive = false; paused = true; cancelAnimationFrame(rafId); } }
  function resume() { if (!isActive && paused) { isActive = true; paused = false; animate(); } }
  return { start, pause, resume, isActive: () => isActive };
}

// ==================== Sizes ====================
class Sizes extends EventEmitter {
  constructor({ canvas }) {
    super();
    this.canvas = canvas;
    this.pixelRatio = Math.min(window.devicePixelRatio, 2);
    this.init();
    window.addEventListener('resize', () => { this.init(); this.emit('resize'); });
  }
  init() {
    const parent = this.canvas.parentNode;
    this.width = parent ? parent.offsetWidth : window.innerWidth;
    this.height = parent ? parent.offsetHeight : window.innerHeight;
    this.pixelRatio = Math.min(window.devicePixelRatio, 2);
  }
  destroy() { this.off('resize'); }
}

// ==================== Time ====================
class Time extends EventEmitter {
  constructor() {
    super();
    this.start = Date.now();
    this.current = this.start;
    this.elapsed = 0;
    this.delta = 16;
    this.clock = new THREE.Clock();
    this.raf = RafFn(() => this.tick());
    this.raf.start();
  }
  tick() {
    const currentTime = Date.now();
    this.delta = currentTime - this.current;
    this.current = currentTime;
    this.elapsed = this.current - this.start;
    const delta = this.clock.getDelta();
    const elapsedTime = this.clock.getElapsedTime();
    this.emit('tick', delta, elapsedTime);
  }
  destroy() { this.raf.pause(); this.off('tick'); }
  pause() { this.raf.pause(); }
  resume() { this.raf.resume(); }
  isActive() { return this.raf.isActive(); }
}

// ==================== Camera ====================
class Camera {
  constructor({ sizes, scene, canvas }, options = { isOrthographic: false }) {
    this.sizes = sizes; this.scene = scene; this.canvas = canvas;
    this.options = Object.assign({ isOrthographic: false }, options);
    this.setInstance();
  }
  setInstance() {
    const aspect = this.sizes.width / this.sizes.height;
    if (this.options.isOrthographic) {
      const s = 120;
      this.instance = new THREE.OrthographicCamera(-s * aspect, s * aspect, s, -s, 1, 10000);
    } else {
      this.instance = new THREE.PerspectiveCamera(45, aspect, 1, 10000);
    }
    this.instance.position.set(10, 10, 10);
    this.scene.add(this.instance);
    this.setControls();
  }
  setControls() {
    const Ctrl = THREE.OrbitControls || window.OrbitControls;
    this.controls = Ctrl ? new Ctrl(this.instance, this.canvas) : null;
    if (!this.controls) {
      // fallback: import from CDN
      import('three/addons/controls/OrbitControls.js').then(mod => {
        this.controls = new mod.OrbitControls(this.instance, this.canvas);
        this.controls.enableDamping = true;
        this.controls.update();
      });
      return;
    }
    this.controls.enableDamping = true;
    this.controls.update();
  }
  resize() {
    const aspect = this.sizes.width / this.sizes.height;
    if (this.options.isOrthographic) {
      const s = 120;
      this.instance.left = -s * aspect; this.instance.right = s * aspect;
      this.instance.top = s; this.instance.bottom = -s;
    } else {
      this.instance.aspect = aspect;
    }
    this.instance.updateProjectionMatrix();
  }
  update() { this.controls && this.controls.update(); }
  destroy() { this.controls && this.controls.dispose(); }
}

// ==================== Renderer ====================
class Renderer {
  constructor({ canvas, sizes, scene, camera }) {
    this.canvas = canvas; this.sizes = sizes; this.scene = scene; this.camera = camera;
    this.setInstance();
  }
  setInstance() {
    this.instance = new THREE.WebGLRenderer({
      alpha: true,
      antialias: true,
      canvas: this.canvas,
    });
    this.instance.setSize(this.sizes.width, this.sizes.height);
    this.instance.setPixelRatio(this.sizes.pixelRatio);
  }
  resize() {
    this.instance.setSize(this.sizes.width, this.sizes.height);
    this.instance.setPixelRatio(this.sizes.pixelRatio);
  }
  update() { this.instance.render(this.scene, this.camera.instance); }
  destroy() { this.instance.dispose(); this.instance.forceContextLoss(); }
}

// ==================== Mini3d ====================
class Mini3d extends EventEmitter {
  constructor(canvas, config = {}) {
    super();
    const defaultConfig = { isOrthographic: false };
    this.config = Object.assign({}, defaultConfig, config);
    this.canvas = canvas;
    this.scene = new THREE.Scene();
    this.sizes = new Sizes(this);
    this.time = new Time(this);
    this.camera = new Camera(this, { isOrthographic: this.config.isOrthographic });
    this.renderer = new Renderer(this);
    this.sizes.on('resize', () => this.resize());
    this.time.on('tick', (delta) => this.update(delta));
  }
  setAxesHelper(size = 250) {
    if (!size) return false;
    this.scene.add(new THREE.AxesHelper(size));
  }
  resize() { this.camera.resize(); this.renderer.resize(); }
  update(delta) { this.camera.update(); this.renderer.update(); }
  destroy() {
    this.sizes.destroy(); this.time.destroy(); this.camera.destroy(); this.renderer.destroy();
    this.scene.traverse((child) => {
      if (child instanceof THREE.Mesh) {
        child.geometry.dispose();
        for (const key in child.material) {
          const value = child.material[key];
          if (value && typeof value.dispose === 'function') value.dispose();
        }
      }
    });
    if (this.canvas.parentNode) this.canvas.parentNode.removeChild(this.canvas);
  }
}

// ==================== Utility Functions ====================
function transfromMapGeoJSON(data) {
  let worldData = typeof data === 'string' ? JSON.parse(data) : data;
  let features = worldData.features;
  for (let i = 0; i < features.length; i++) {
    const element = features[i];
    if (['Polygon'].includes(element.geometry.type)) {
      element.geometry.coordinates = [element.geometry.coordinates];
    }
  }
  return worldData;
}

function getBoundBox(group) {
  var size = new THREE.Vector3();
  var box3 = new THREE.Box3();
  box3.expandByObject(group);
  var boxSize = new THREE.Vector3();
  box3.getSize(boxSize);
  var center = new THREE.Vector3();
  box3.getCenter(center);
  let obj = { box3, boxSize, center };
  if (group.geometry) {
    group.geometry.computeBoundingBox();
    group.geometry.computeBoundingSphere();
    const { max, min } = group.geometry.boundingBox;
    size.x = max.x - min.x; size.y = max.y - min.y; size.z = max.z - min.z;
    obj.size = size;
  }
  return obj;
}

function uuid(len = 10, radix = 62) {
  var chars = '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz'.split('');
  var uuid = [], i;
  radix = radix || chars.length;
  if (len) { for (i = 0; i < len; i++) uuid[i] = chars[0 | (Math.random() * radix)]; }
  else {
    var r;
    uuid[8] = uuid[13] = uuid[18] = uuid[23] = '-'; uuid[14] = '4';
    for (i = 0; i < 36; i++) {
      if (!uuid[i]) { r = 0 | (Math.random() * 16); uuid[i] = chars[i === 19 ? (r & 0x3) | 0x8 : r]; }
    }
  }
  return uuid.join('');
}

function emptyObject(obj) {
  while (obj.children.length > 0) {
    let child = obj.children[0];
    if (child.geometry) child.geometry.dispose();
    if (child.material) {
      if (Array.isArray(child.material)) {
        child.material.forEach(m => { if (m.map) m.map.dispose(); m.dispose(); });
      } else {
        if (child.material.map) child.material.map.dispose();
        child.material.dispose();
      }
    }
    obj.remove(child);
  }
}

// Simple point-in-polygon (ray casting algorithm)
function pointInPolygon(point, polygon) {
  const x = point[0], y = point[1];
  let inside = false;
  for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i++) {
    const xi = polygon[i][0], yi = polygon[i][1];
    const xj = polygon[j][0], yj = polygon[j][1];
    if ((yi > y) !== (yj > y) && x < (xj - xi) * (y - yi) / (yj - yi) + xi) {
      inside = !inside;
    }
  }
  return inside;
}

function minBy(data, getter) {
  let minItem = data[0];
  for (let i = 1; i < data.length; i++) { if (getter(data[i]) < getter(minItem)) minItem = data[i]; }
  return minItem;
}

function maxBy(data, getter) {
  let maxItem = data[0];
  for (let i = 1; i < data.length; i++) { if (getter(data[i]) > getter(maxItem)) maxItem = data[i]; }
  return maxItem;
}

function generateGrid(coordinates, gap = 3) {
  let coords = coordinates.map(item => [item.x, item.y]);
  let minLon = Math.floor(minBy(coordinates, o => o.x).x);
  let maxLon = Math.ceil(maxBy(coordinates, o => o.x).x);
  let minLat = Math.floor(minBy(coordinates, o => o.y).y);
  let maxLat = Math.ceil(maxBy(coordinates, o => o.y).y);
  let lonScope = Math.ceil((maxLon - minLon) / gap);
  let latScope = Math.ceil((maxLat - minLat) / gap);
  let scopePoint = [];
  for (let i = 0; i < lonScope + 1; i++) {
    let x = minLon + i * gap;
    for (let j = 0; j < latScope + 1; j++) {
      scopePoint.push([x, minLat + j * gap]);
    }
  }
  let scopeInsidePoint = scopePoint
    .filter(item => pointInPolygon(item, coords))
    .map(item => new THREE.Vector3(item[0], item[1], 0));
  return { scopeInsidePoint, scopePoint };
}

// ==================== GradientShader ====================
class GradientShader {
  constructor(material, config) {
    this.shader = null;
    this.config = Object.assign({
      uColor1: 0x2a6f72, uColor2: 0x0d2025, size: 15.0, dir: 'x',
    }, config);
    this.init(material);
  }
  init(material) {
    let { uColor1, uColor2, dir, size } = this.config;
    let dirMap = { x: 1.0, y: 2.0, z: 3.0 };
    material.onBeforeCompile = (shader) => {
      this.shader = shader;
      shader.uniforms = {
        ...shader.uniforms,
        uColor1: { value: new THREE.Color(uColor1) },
        uColor2: { value: new THREE.Color(uColor2) },
        uDir: { value: dirMap[dir] },
        uSize: { value: size },
      };
      shader.vertexShader = shader.vertexShader.replace('void main() {', `
        attribute float alpha;
        varying vec3 vPosition;
        varying float vAlpha;
        void main() {
          vAlpha = alpha;
          vPosition = position;
      `);
      shader.fragmentShader = shader.fragmentShader.replace('void main() {', `
        varying vec3 vPosition;
        varying float vAlpha;
        uniform vec3 uColor1;
        uniform vec3 uColor2;
        uniform float uDir;
        uniform float uSize;
        void main() {
      `);
      shader.fragmentShader = shader.fragmentShader.replace('#include <opaque_fragment>', /* glsl */ `
        #ifdef OPAQUE
        diffuseColor.a = 1.0;
        #endif
        #ifdef USE_TRANSMISSION
        diffuseColor.a *= transmissionAlpha + 0.1;
        #endif
        vec3 gradient = vec3(0.0,0.0,0.0);
        if(uDir==1.0){ gradient = mix(uColor1, uColor2, vPosition.x/uSize); }
        else if(uDir==2.0){ gradient = mix(uColor1, uColor2, vPosition.z/uSize); }
        else if(uDir==3.0){ gradient = mix(uColor1, uColor2, vPosition.y/uSize); }
        outgoingLight = outgoingLight * gradient;
        gl_FragColor = vec4(outgoingLight, diffuseColor.a);
      `);
    };
  }
}

// ==================== DiffuseShader ====================
class DiffuseShader {
  constructor({ material, time, size, diffuseColor, diffuseSpeed, diffuseWidth, callback = () => {} }) {
    this.time = time;
    this.pointShader = null;
    this.callback = callback;
    this.options = Object.assign({
      size: 100, diffuseSpeed: 15.0, diffuseColor: 0x8e9b9e, diffuseWidth: 10.0,
    }, { material, size, diffuseColor, diffuseSpeed, diffuseWidth });
    this.init();
  }
  init() {
    let { material, size, diffuseColor, diffuseSpeed, diffuseWidth } = this.options;
    let maxTime = size / diffuseSpeed;
    material.onBeforeCompile = (shader) => {
      this.pointShader = shader;
      this.callback(shader, maxTime);
      shader.uniforms = {
        ...shader.uniforms,
        uTime: { value: 0.0 },
        uSpeed: { value: diffuseSpeed },
        uWidth: { value: diffuseWidth },
        uColor: { value: new THREE.Color(diffuseColor) },
      };
      shader.vertexShader = shader.vertexShader.replace('void main() {', `
        varying vec3 vPosition;
        void main(){ vPosition = position;
      `);
      shader.fragmentShader = shader.fragmentShader.replace('void main() {', `
        uniform float uTime;
        uniform float uSpeed;
        uniform float uWidth;
        uniform vec3 uColor;
        varying vec3 vPosition;
        void main(){
      `);
      shader.fragmentShader = shader.fragmentShader.replace('#include <opaque_fragment>', /* glsl */ `
        #ifdef OPAQUE
        diffuseColor.a = 1.0;
        #endif
        #ifdef USE_TRANSMISSION
        diffuseColor.a *= material.transmissionAlpha;
        #endif
        float r = uTime * uSpeed;
        float w = uWidth;
        vec2 center = vec2(0.0, 0.0);
        float rDistance = distance(vPosition.xy, center);
        if(rDistance > r && rDistance < r + 2.0 * w) {
          float per = 0.0;
          if(rDistance < r + w) {
            float p = smoothstep(0.0,1.0,(rDistance - r) / w);
            p*=p;
            outgoingLight = mix(outgoingLight, uColor, p);
          } else {
            float p = smoothstep(0.0,1.0,(rDistance - r - w) / w);
            outgoingLight = mix(uColor, outgoingLight, p);
          }
          gl_FragColor = vec4(outgoingLight, diffuseColor.a);
        } else {
          gl_FragColor = vec4(outgoingLight, 0.0);
        }
      `);
    };
  }
}

// ==================== BaseMap (平面地图) ====================
class BaseMap {
  constructor(projectionFn, config = {}) {
    this.mapGroup = new THREE.Group();
    this.coordinates = [];
    this.config = Object.assign({
      position: new THREE.Vector3(0, 0, 0),
      data: '',
      renderOrder: 1,
      merge: false,
      material: new THREE.MeshBasicMaterial({ color: 0x18263b, transparent: true, opacity: 1 }),
    }, config);
    this.geoProject = projectionFn;
    this.mapGroup.position.copy(this.config.position);
    let mapData = transfromMapGeoJSON(this.config.data);
    this.create(mapData);
  }
  create(mapData) {
    let { merge } = this.config;
    let shapes = [];
    mapData.features.forEach((feature) => {
      const group = new THREE.Object3D();
      let { name, center = [], centroid = [] } = feature.properties;
      this.coordinates.push({ name, center, centroid });
      group.userData.name = name;
      feature.geometry.coordinates.forEach((multiPolygon) => {
        multiPolygon.forEach((polygon) => {
          const shape = new THREE.Shape();
          for (let i = 0; i < polygon.length; i++) {
            if (!polygon[i][0] || !polygon[i][1]) return false;
            const [x, y] = this.geoProject(polygon[i]);
            if (i === 0) shape.moveTo(x, -y);
            shape.lineTo(x, -y);
          }
          const geometry = new THREE.ShapeGeometry(shape);
          if (merge) {
            shapes.push(geometry);
          } else {
            const mesh = new THREE.Mesh(geometry, this.config.material);
            mesh.renderOrder = this.config.renderOrder;
            mesh.userData.name = name;
            group.add(mesh);
          }
        });
      });
      if (!merge) this.mapGroup.add(group);
    });
    if (merge && shapes.length > 0) {
      // Simple merge — just add all shapes to group
      shapes.forEach(g => {
        const mesh = new THREE.Mesh(g, this.config.material);
        mesh.renderOrder = this.config.renderOrder;
        this.mapGroup.add(mesh);
      });
    }
  }
  getCoordinates() { return this.coordinates; }
  setParent(parent) { parent.add(this.mapGroup); }
}

// ==================== ExtrudeMap (3D挤出地图) ====================
class ExtrudeMap {
  constructor(projectionFn, config = {}) {
    this.mapGroup = new THREE.Group();
    this.coordinates = [];
    this.config = Object.assign({
      position: new THREE.Vector3(0, 0, 0),
      data: '',
      renderOrder: 1,
      topFaceMaterial: new THREE.MeshBasicMaterial({ color: 0x18263b, transparent: true, opacity: 1 }),
      sideMaterial: new THREE.MeshBasicMaterial({ color: 0x07152b, transparent: true, opacity: 1 }),
      depth: 0.1,
    }, config);
    this.geoProject = projectionFn;
    this.mapGroup.position.copy(this.config.position);
    let mapData = transfromMapGeoJSON(this.config.data);
    this.create(mapData);
  }
  create(mapData) {
    mapData.features.forEach((feature) => {
      const group = new THREE.Object3D();
      let { name, center = [], centroid = [] } = feature.properties;
      this.coordinates.push({ name, center, centroid });
      const extrudeSettings = { depth: this.config.depth, bevelEnabled: true, bevelSegments: 1, bevelThickness: 0.1 };
      let materials = [this.config.topFaceMaterial, this.config.sideMaterial];
      feature.geometry.coordinates.forEach((multiPolygon) => {
        multiPolygon.forEach((polygon) => {
          const shape = new THREE.Shape();
          for (let i = 0; i < polygon.length; i++) {
            if (!polygon[i][0] || !polygon[i][1]) return false;
            const [x, y] = this.geoProject(polygon[i]);
            if (i === 0) shape.moveTo(x, -y);
            shape.lineTo(x, -y);
          }
          const geometry = new THREE.ExtrudeGeometry(shape, extrudeSettings);
          const mesh = new THREE.Mesh(geometry, materials);
          group.add(mesh);
        });
      });
      this.mapGroup.add(group);
    });
  }
  getCoordinates() { return this.coordinates; }
  setParent(parent) { parent.add(this.mapGroup); }
}

// ==================== Line (线条/轮廓) ====================
class Line {
  constructor(projectionFn, config = {}) {
    this.config = Object.assign({
      visibelProvince: '',
      position: new THREE.Vector3(0, 0, 0),
      data: '',
      material: new THREE.LineBasicMaterial({ color: 0xffffff }),
      type: 'LineLoop',
      renderOrder: 1,
      tubeRadius: 0.2,
    }, config);
    this.geoProject = projectionFn;
    let mapData = transfromMapGeoJSON(this.config.data);
    let lineGroup = this.create(mapData);
    this.lineGroup = lineGroup;
    this.lineGroup.position.copy(this.config.position);
  }
  create(data) {
    const { type, visibelProvince } = this.config;
    let features = data.features;
    let lineGroup = new THREE.Group();
    for (let i = 0; i < features.length; i++) {
      const element = features[i];
      let group = new THREE.Group();
      group.name = 'meshLineGroup' + i;
      if (element.properties.name === visibelProvince) continue;
      element.geometry.coordinates.forEach((coords) => {
        const points = [];
        let line = null;
        if (type === 'Line3') {
          coords[0].forEach((item) => {
            const [x, y] = this.geoProject(item);
            points.push(new THREE.Vector3(x, -y, 0));
          });
          line = this.createLine3(points);
        } else if (type === 'Line2') {
          coords[0].forEach((item) => {
            const [x, y] = this.geoProject(item);
            points.push(x, -y, 0);
          });
          line = this.createLine2(points);
        } else {
          coords[0].forEach((item) => {
            const [x, y] = this.geoProject(item);
            points.push(new THREE.Vector3(x, -y, 0));
          });
          line = this.createLine(points);
        }
        group.add(line);
      });
      lineGroup.add(group);
    }
    return lineGroup;
  }
  createLine3(points) {
    const { material, renderOrder } = this.config;
    const curve = new THREE.CatmullRomCurve3(points);
    const tubeGeometry = new THREE.TubeGeometry(curve, 256 * 10, this.config.tubeRadius, 4, false);
    const line = new THREE.Mesh(tubeGeometry, material);
    line.name = 'mapLine3';
    line.renderOrder = renderOrder;
    return line;
  }
  createLine2(points) {
    // Simplified: use LineLoop instead of Line2 (fat lines not available without addon)
    const geom = new THREE.BufferGeometry();
    geom.setFromPoints(points.map(p => new THREE.Vector3(p[0], p[1], p[2])));
    const line = new THREE.LineLoop(geom, this.config.material);
    line.renderOrder = this.config.renderOrder;
    return line;
  }
  createLine(points) {
    const geometry = new THREE.BufferGeometry();
    geometry.setFromPoints(points);
    let line = new THREE.LineLoop(geometry, this.config.material);
    line.renderOrder = this.config.renderOrder;
    line.name = 'mapLine';
    return line;
  }
  setParent(parent) { parent.add(this.lineGroup); }
}

// ==================== FlyLine (飞线) ====================
class FlyLine {
  constructor(time, geoProjectionFn, options) {
    this.time = time;
    this.geoProject = geoProjectionFn;
    this.instance = new THREE.Group();
    let defaultOptions = {
      centerPoint: [0, 0], middleHeight: 15, speed: 0.003,
      texture: null, radius: 0.1, segments: 32, radialSegments: 8,
      data: [],
      material: new THREE.MeshBasicMaterial({
        color: 0xfbdf88, transparent: true, fog: false, opacity: 1,
        depthTest: false, blending: THREE.AdditiveBlending,
      }),
    };
    this.options = Object.assign({}, defaultOptions, options);
    this.run = true;
    this.init();
  }
  init() {
    const { centerPoint, material, texture, segments, radius, radialSegments, data, speed, middleHeight } = this.options;
    let [centerX, centerY] = this.geoProject(centerPoint);
    let centerPointVec = new THREE.Vector3(centerX, -centerY, 0);
    data.forEach((city) => {
      let [x, y] = this.geoProject(city.centroid);
      let point = new THREE.Vector3(x, -y, 0);
      const center = new THREE.Vector3();
      center.addVectors(centerPointVec, point).multiplyScalar(0.5);
      center.setZ(middleHeight);
      const curve = new THREE.QuadraticBezierCurve3(centerPointVec, center, point);
      const tubeGeometry = new THREE.TubeGeometry(curve, segments, radius, radialSegments, false);
      const mesh = new THREE.Mesh(tubeGeometry, material);
      mesh.position.set(0, 0, 0);
      mesh.renderOrder = 21;
      this.instance.add(mesh);
    });
    this.time.on('tick', () => {
      if (this.run && texture) { texture.offset.x -= speed; }
    });
  }
  getInstance() { return this.instance; }
  setParent(parent) { parent.add(this.instance); }
  set visible(bool) { this.instance.visible = bool; this.run = bool; }
}

// ==================== Focus (聚焦光圈，依赖 GSAP) ====================
class Focus extends THREE.Object3D {
  constructor(textures, config) {
    super();
    this.config = Object.assign({ color1: 0xfcc957, color2: 0xffffff }, config);
    this.textures = textures;
    this.gsapObjects = [];
    this.animateElements = {};
    this.init();
  }
  init() {
    let color = this.config.color1;
    let geometry = new THREE.PlaneGeometry(1.5, 1.5, 1);
    let barGeometry = new THREE.PlaneGeometry(1, 3, 1);
    barGeometry.translate(0, 1, 0);
    let material = new THREE.MeshBasicMaterial({
      color, transparent: true, fog: false, side: THREE.DoubleSide, depthWrite: false,
    });
    let focusArrowsMaterial = material.clone();
    focusArrowsMaterial.map = this.textures.focusArrows;
    let focusBarMaterial = material.clone();
    focusBarMaterial.map = this.textures.focusBar;
    let focusBgMaterial = material.clone();
    focusBgMaterial.map = this.textures.focusBg;
    let focusMidQuanMaterial = material.clone();
    focusMidQuanMaterial.color = new THREE.Color(this.config.color2);
    focusMidQuanMaterial.map = this.textures.focusMidQuan;
    let focusMoveBgMaterial = material.clone();
    focusMoveBgMaterial.map = this.textures.focusMoveBg;
    focusMoveBgMaterial.blending = THREE.AdditiveBlending;

    let focusArrows = new THREE.Mesh(geometry, focusArrowsMaterial);
    let focusBar1 = new THREE.Mesh(barGeometry, focusBarMaterial);
    focusBar1.rotation.x = Math.PI / 2;
    let focusBar2 = focusBar1.clone();
    focusBar2.rotation.y = Math.PI / 2;
    let focusBg = new THREE.Mesh(geometry, focusBgMaterial);
    let focusMidQuan = new THREE.Mesh(geometry, focusMidQuanMaterial);
    let focusMoveBg = new THREE.Mesh(geometry, focusMoveBgMaterial);

    [focusMidQuan, focusBg, focusArrows, focusMoveBg, focusBar1, focusBar2].forEach(el => { el.renderOrder = 99; });
    this.add(focusMidQuan, focusBg, focusArrows, focusMoveBg, focusBar1, focusBar2);
    focusMoveBg.scale.setScalar(0);
    this.animateElements = { focusMidQuan, focusArrows, focusMoveBg };
    this.startAnimate();
  }
  startAnimate() {
    if (typeof gsap === 'undefined') return;
    let quanTween = gsap.to(this.animateElements.focusMidQuan.rotation, { z: 2 * Math.PI, duration: 8, repeat: -1, ease: 'none' });
    let arrowsTween = gsap.to(this.animateElements.focusArrows.rotation, { z: 2 * Math.PI, duration: 5, repeat: -1, ease: 'none' });
    let moveBgScaleTween = gsap.to(this.animateElements.focusMoveBg.scale, { x: 1.5, y: 1.5, z: 1.5, duration: 2.5, repeat: -1, ease: 'none' });
    let moveBgMatTween = gsap.to(this.animateElements.focusMoveBg.material, { opacity: 0, duration: 2.5, repeat: -1, ease: 'none' });
    this.gsapObjects = [quanTween, arrowsTween, moveBgScaleTween, moveBgMatTween];
  }
  pausedAnimate() { this.gsapObjects.forEach(el => { el.paused = true; }); }
  destroy() {
    this.gsapObjects.forEach(el => { el.kill(); });
    emptyObject(this);
  }
}

// ==================== Particles (粒子系统) ====================
class Particles {
  constructor(time, config = {}) {
    this.instance = null;
    this.time = time;
    this.enable = true;
    this.config = Object.assign({
      num: 100, range: 500, speed: 0.01, renderOrder: 99, dir: 'up',
      material: new THREE.PointsMaterial({
        map: Particles.createTexture(),
        size: 20, color: 0xffffff, transparent: true, opacity: 1.0,
        depthTest: false, vertexColors: true, blending: THREE.AdditiveBlending, sizeAttenuation: true,
      }),
    }, config);
    this.create();
  }
  create() {
    const { range, material, num, renderOrder } = this.config;
    const position = [], colors = [], velocities = [];
    for (let i = 0; i < num; i++) {
      position.push(
        Math.random() * range - range / 2,
        Math.random() * range - range / 2,
        Math.random() * range - range / 2
      );
      velocities.push(Math.random(), (0.1 + Math.random()), 0.1 + Math.random());
      const color = material.color.clone();
      let hsl = {}; color.getHSL(hsl); color.setHSL(hsl.h, hsl.s, hsl.l * Math.random());
      colors.push(color.r, color.g, color.b);
    }
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position', new THREE.BufferAttribute(new Float32Array(position), 3));
    geometry.setAttribute('velocities', new THREE.BufferAttribute(new Float32Array(velocities), 3));
    geometry.setAttribute('color', new THREE.BufferAttribute(new Float32Array(colors), 3));
    this.instance = new THREE.Points(geometry, material);
    this.instance.renderOrder = renderOrder;
  }
  static createTexture() {
    let canvas = document.createElement('canvas');
    canvas.width = 1024; canvas.height = 1024;
    let context = canvas.getContext('2d');
    let gradient = context.createRadialGradient(512, 512, 0, 512, 512, 512);
    gradient.addColorStop(0, 'rgba(255,255,255,1)');
    gradient.addColorStop(1, 'rgba(255,255,255,0)');
    context.fillStyle = gradient; context.fillRect(0, 0, 1024, 1024);
    return new THREE.CanvasTexture(canvas);
  }
  update(delta, elapsedTime) {
    if (!this.instance) return false;
    const { range, speed, dir } = this.config;
    let dirVec = dir === 'up' ? 1 : -1;
    let position = this.instance.geometry.getAttribute('position');
    let velocities = this.instance.geometry.getAttribute('velocities');
    const count = position.count;
    for (let i = 0; i < count; i++) {
      let pos_x = position.getX(i), pos_z = position.getZ(i);
      let vel_x = velocities.getX(i);
      pos_x += Math.sin(vel_x * elapsedTime) * delta;
      pos_z += speed * dirVec;
      if (pos_z > range / 2 && dirVec === 1) pos_z = -range / 2;
      if (pos_z < -range / 2 && dirVec === -1) pos_z = range / 2;
      position.setX(i, pos_x);
      position.setZ(i, pos_z);
    }
    position.needsUpdate = true;
    velocities.needsUpdate = true;
  }
  setParent(parent) {
    parent.add(this.instance);
    this.time.on('tick', (delta, elapsedTime) => { if (this.enable) this.update(delta, elapsedTime); });
  }
}

// ==================== Plane (旋转平面) ====================
class Plane {
  constructor(time, options) {
    this.time = time;
    this.options = Object.assign({
      width: 10, scale: 1,
      position: new THREE.Vector3(0, 0, 0),
      needRotate: false, rotateSpeed: 0.001,
      material: new THREE.MeshBasicMaterial({ transparent: true, opacity: 1, depthTest: true }),
    }, options);
    let planeGeo = new THREE.PlaneGeometry(this.options.width, this.options.width);
    let mesh = new THREE.Mesh(planeGeo, this.options.material);
    mesh.position.copy(this.options.position);
    mesh.scale.set(this.options.scale, this.options.scale, this.options.scale);
    this.instance = mesh;
  }
  setParent(parent) {
    parent.add(this.instance);
    this.time.on('tick', () => { this.update(); });
  }
  update() {
    if (this.options.needRotate) { this.instance.rotation.z += this.options.rotateSpeed; }
  }
}

// ==================== Grid (网格背景) ====================
class Grid {
  constructor(scene, time, options) {
    this.scene = scene; this.time = time; this.instance = null;
    this.options = Object.assign({
      position: new THREE.Vector3(0, 0, 0),
      gridSize: 100, gridDivision: 20, gridColor: 0x28373a,
      shapeSize: 1, shapeColor: 0x8e9b9e,
      pointSize: 0.2, pointColor: 0x28373a,
      pointLayout: { row: 200, col: 200 },
      pointBlending: THREE.NormalBlending,
    }, options);
    this.init();
  }
  init() {
    let group = new THREE.Group();
    group.name = 'Grid';
    let grid = this.createGridHelp();
    let shapes = this.createShapes();
    let points = this.createPoint();
    group.add(grid, shapes, points);
    group.position.copy(this.options.position);
    this.instance = group;
    this.scene.add(group);
  }
  createShapes() {
    let { gridSize, gridDivision, shapeSize, shapeColor } = this.options;
    let shapeSpace = gridSize / gridDivision;
    let range = gridSize / 2;
    let shapeMaterial = new THREE.MeshBasicMaterial({ color: shapeColor, side: THREE.DoubleSide });
    let shapeGroup = new THREE.Group();
    for (let i = 0; i < gridDivision + 1; i++) {
      for (let j = 0; j < gridDivision + 1; j++) {
        let shapeGeometry = this.createPlus(shapeSize);
        shapeGeometry.translate(-range + i * shapeSpace, -range + j * shapeSpace, 0);
        let mesh = new THREE.Mesh(shapeGeometry, shapeMaterial);
        mesh.renderOrder = -1;
        shapeGroup.add(mesh);
      }
    }
    shapeGroup.rotateX(-Math.PI / 2);
    shapeGroup.position.y += 0.01;
    return shapeGroup;
  }
  createGridHelp() {
    let { gridSize, gridDivision, gridColor } = this.options;
    return new THREE.GridHelper(gridSize, gridDivision, gridColor, gridColor);
  }
  createPoint() {
    let { gridSize, pointSize, pointColor, pointBlending, pointLayout } = this.options;
    const rows = pointLayout.row, cols = pointLayout.col;
    const positions = new Float32Array(rows * cols * 3);
    for (let i = 0; i < rows; i++) {
      for (let j = 0; j < cols; j++) {
        let x = (i / (rows - 1)) * gridSize - gridSize / 2;
        let z = (j / (cols - 1)) * gridSize - gridSize / 2;
        let index = (i * cols + j) * 3;
        positions[index] = x; positions[index + 1] = 0; positions[index + 2] = z;
      }
    }
    var geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
    return new THREE.Points(geometry, new THREE.PointsMaterial({
      size: pointSize, sizeAttenuation: true, color: pointColor, blending: pointBlending,
    }));
  }
  createPlus(shapeSize = 50) {
    let w = shapeSize / 6 / 3, h = shapeSize / 3;
    let pts = [
      new THREE.Vector2(-h, -w), new THREE.Vector2(-w, -w), new THREE.Vector2(-w, -h),
      new THREE.Vector2(w, -h), new THREE.Vector2(w, -w), new THREE.Vector2(h, -w),
      new THREE.Vector2(h, w), new THREE.Vector2(w, w), new THREE.Vector2(w, h),
      new THREE.Vector2(-w, h), new THREE.Vector2(-w, w), new THREE.Vector2(-h, w),
    ];
    return new THREE.ShapeGeometry(new THREE.Shape(pts), 24);
  }
}

// ==================== Label3d (CSS3D 标签) ====================
class Label3d {
  constructor({ scene, camera, time, sizes, canvas }) {
    this.scene = scene; this.camera = camera; this.time = time;
    this.sizes = sizes; this.canvas = canvas; this.parent = null;
    let { width, height } = this.sizes;
    let css3dRender = new CSS3DRenderer();
    this.css3dRender = css3dRender;
    css3dRender.setSize(width, height);
    css3dRender.domElement.style.position = 'absolute';
    css3dRender.domElement.style.left = '0px';
    css3dRender.domElement.style.top = '0px';
    css3dRender.domElement.style.pointerEvents = 'none';
    css3dRender.domElement.className = 'label3d-' + uuid();
    this.canvas.parentNode.appendChild(css3dRender.domElement);
    this.time.on('tick', () => this.update());
    this.sizes.on('resize', () => this.resize());
  }
  create(content = '', className = '', isSprite = false) {
    let tag = document.createElement('div');
    tag.innerHTML = content;
    tag.className = className;
    tag.style.visibility = 'hidden';
    tag.style.position = 'absolute';
    if (!className) {
      tag.style.padding = '10px'; tag.style.color = '#fff'; tag.style.fontSize = '12px';
      tag.style.textAlign = 'center'; tag.style.background = 'rgba(0,0,0,0.6)'; tag.style.borderRadius = '4px';
    }
    let label = isSprite ? new CSS3DSprite(tag) : new CSS3DObject(tag);
    label.init = (content, position) => {
      label.element.innerHTML = content;
      label.element.style.visibility = 'visible';
      label.position.copy(position);
    };
    label.hide = () => { label.element.style.visibility = 'hidden'; };
    label.show = () => { label.element.style.visibility = 'visible'; };
    label.setParent = (parent) => { this.parent = parent; parent.add(label); };
    label.remove = () => { if (this.parent) this.parent.remove(label); };
    return label;
  }
  setLabelStyle(label, scale = 0.1, axis = 'x', axisRotation = Math.PI / 2, pointerEvents = 'none') {
    label.element.style.pointerEvents = pointerEvents;
    label.scale.set(scale, scale, scale);
    label.rotation[axis] = axisRotation;
  }
  setRenderLevel(zIndex) { this.css3dRender.domElement.style.zIndex = zIndex; }
  update() { this.css3dRender.render(this.scene, this.camera.instance); }
  destroy() {
    if (this.css3dRender) {
      let domElement = this.css3dRender.domElement;
      if (domElement.parentNode) domElement.parentNode.removeChild(domElement);
    }
  }
  resize() {
    let { width, height } = this.sizes;
    this.css3dRender.setSize(width, height);
  }
}

// ==================== Resource Loader ====================
class Resource extends EventEmitter {
  constructor() {
    super();
    this.itemsLoaded = 0;
    this.itemsTotal = 0;
    this.assets = [];
    this.loaders = {};
    this.textureLoader = new THREE.TextureLoader();
    this.fileLoader = new THREE.FileLoader();
  }
  async loadAll(assets) {
    this.itemsTotal = assets.length;
    this.itemsLoaded = 0;
    const results = [];
    for (const item of assets) {
      try {
        let data;
        if (item.type === 'Texture') {
          data = await this.textureLoader.loadAsync(item.path);
        } else if (item.type === 'File') {
          data = await this.fileLoader.loadAsync(item.path);
        }
        this.itemsLoaded++;
        this.emit('onProgress', item.path, this.itemsLoaded, this.itemsTotal);
        results.push({ ...item, data });
      } catch (err) {
        this.emit('onError', err);
      }
    }
    this.assets = results;
    this.emit('onLoad');
    return results;
  }
  getResource(name) {
    let current = this.assets.find(item => item.name === name);
    if (!current) { console.warn('Resource not found:', name); return null; }
    return current.data;
  }
  destroy() {
    this.off('onProgress'); this.off('onLoad'); this.off('onError');
    this.assets = [];
  }
}

// ==================== Exports ====================
export {
  Mini3d, EventEmitter, RafFn, Sizes, Time, Camera, Renderer,
  ExtrudeMap, BaseMap, Line, FlyLine, Focus, Particles, Plane, Grid, Label3d,
  GradientShader, DiffuseShader, Resource,
  transfromMapGeoJSON, getBoundBox, uuid, emptyObject, generateGrid,
  minBy, maxBy, pointInPolygon,
};
