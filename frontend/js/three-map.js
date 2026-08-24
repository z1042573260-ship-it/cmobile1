/**
 * YantaiMap3D — 烟台 Three.js 3D 地图
 * 视觉参数完全对齐 ThreeMaps 广东地图
 * 依赖：mini3d.js 引擎 + Three.js CDN + d3-geo CDN + GSAP CDN
 */
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import {
  ExtrudeMap, BaseMap, Line, FlyLine, Focus,
  Particles, Plane, Grid, Label3d,
  GradientShader, DiffuseShader, Resource,
} from './lib/mini3d.js';

const TEX = 'js/lib/textures';

class YantaiMap3D {
  constructor(container) {
    this.container = container;
    // 使用容器尺寸（autofit 后为 1920×1080），而非 window 尺寸
    this.width = container.clientWidth || window.innerWidth;
    this.height = container.clientHeight || window.innerHeight;
    this.clock = new THREE.Clock();

    // 烟台投影 .center([121.39, 37.52])  scale420
    this.projection = d3.geoMercator()
      .center([121.39, 37.52])
      .scale(300)
      .translate([0, 0]);

    // 对齐广东：geoProjection 不取反 Y，直接返回 Mercator [x, y]
    this.geoProject = (lngLat) => this.projection(lngLat);

    // 深度（对齐广东 depth=0.5）
    this.depth = 0.6;

    // ---- Scene (对齐 ThreeMaps: 0x102736) ----
    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color(0x102736);
    this.scene.fog = new THREE.Fog(0x102736, 1, 50);

    // ---- Camera -----13.77, 12.99, 39.28
    this.camera = new THREE.PerspectiveCamera(45, this.width / this.height, 1, 10000);
    this.camera.position.set(-13.77, 9.0, 39.28);  // 降低相机高度，使地图整体上移
    this.camera.lookAt(0, 0, 0);

    // ---- Renderer ----
    this.renderer = new THREE.WebGLRenderer({ alpha: true, antialias: true });
    this.renderer.setSize(this.width, this.height);
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    this.renderer.shadowMap.enabled = true;
    this.container.appendChild(this.renderer.domElement);

    // ---- OrbitControls ----
    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.target.set(0, 0, 0);
    this.controls.enableDamping = true;
    this.controls.dampingFactor = 0.08;
    // 左键=平移拖拽地图（全市/下钻通用），右键=旋转视角，滚轮=缩放
    this.controls.mouseButtons = { LEFT: THREE.MOUSE.PAN, MIDDLE: THREE.MOUSE.DOLLY, RIGHT: THREE.MOUSE.ROTATE };
    this.controls.update();
    // 限制视角：不允许拖到地图下方看到水平背景面 2.8
    this.controls.maxPolarAngle = Math.PI / 3;  // ~64°，防止看到 ocean plane
    this.controls.minPolarAngle = 0;
    // minDistance 必须允许下钻距离：小区县（芝罘/福山/莱山）飞行距离仅 3~4 单位，
    // 若保持 5，飞行结束后 controls.update() 会把相机强制拉回 5 → 镜头"再对齐"跳动
    this.controls.minDistance = 1;
    this.controls.maxDistance = 60;

    // ---- 灯光 (对齐 ThreeMaps) ----
    this._addLights();

    // ---- 地图根节点 ----  X 负值左移，使地图居中在可见区域 -2.5
    this.mapGroup = new THREE.Group();
    this.mapGroup.rotation.x = -Math.PI / 2;
    this.mapGroup.position.set(0, 0.2, 0);  // 对齐广东：地图中心 = 圆环中心 = 原点
    this.scene.add(this.mapGroup);

    // ---- Label3d (CSS3D) ----
    this.label3d = new Label3d({
      scene: this.scene,
      camera: { instance: this.camera },
      time: { on: () => {}, off: () => {} },
      sizes: { width: this.width, height: this.height, on: () => {}, off: () => {} },
      canvas: this.renderer.domElement,
    });
    // CSS3D 标签渲染在 canvas 上方（z-index: 1），但在卡片下方（z-index: 999+）
    this.label3d.setRenderLevel('1');

    this.isDestroyed = false;
    this.intersectMeshes = [];
    this.scatterItems = [];
    this.sideMaterial = null;
    this.strokeMaterial = null;

    // 共享事件发射器（支持多 tick 回调）
    this._tickCallbacks = [];
    this._fakeTime = {
      on: (ev, cb) => { if (ev === 'tick') this._tickCallbacks.push(cb); },
      off: () => { this._tickCallbacks = []; },
      emit: () => {},
    };

    // 预警图 3D 图钉状态（提前初始化，_animate 每帧读取）
    this._warningPinGroup = null;
    this._warningPins = [];
    this._selectedPin = null;   // 选中常显标签的图钉（日志点击/图钉点击）；关闭卡片时清空
    this._pinSolo = null;       // 日志点击 → 只显示该图钉（独显模式）；关闭卡片/切模式恢复全部
    this._focusPrevMode = null; // 日志点击前的地图模式（独显关闭时恢复，如柱状图）
    this._sharedPinGeo = null;
    this._pinTimer = null;
    // ★ 图钉尺寸配置：改这里即可调整大小（改完 F5 刷新生效）
    this._pinConfig = {
      pinScale: 0.12,   // 图钉水滴大小（高度≈pinScale×2.4；图钉多时调小更清爽）0.15
      rippleSize: 0.4,   // 地面波纹光圈直径（世界单位，地图宽约 17；图钉密时调小避免波纹连片）
      pinLift: 0.3,     // 图钉水滴悬浮高度：波纹贴地面不动，水滴在正上方抬起（间距=pinLift，纯竖直）
      floatAmp: 0.17,    // 水滴上下浮动幅度（叠加在悬浮高度上，世界单位，可 F5 微调）0.08
      maxPins: 0,       // 图钉展示上限：0=不限制（所有有预警的图钉都显示，同坐标/同名折叠保留）；>0 按 priority 取前 N
      labelScale: 1.0,   // 悬浮标签缩放（0.8 更小，1.2 更大）
    };
    this._pinLabelLayer = document.createElement('div');
    this._pinLabelLayer.className = 'pin-label-layer';
    document.body.appendChild(this._pinLabelLayer);

    // RAF
    this._animate = this._animate.bind(this);
    this._rafId = requestAnimationFrame(this._animate);
  }

  // ==================== 灯光（对齐 ThreeMaps） ====================
  _addLights() {
    // Ambient: 0xffffff, intensity 5
    this.scene.add(new THREE.AmbientLight(0xffffff, 5));
    // Directional: 0xffffff, intensity 5
    const dir = new THREE.DirectionalLight(0xffffff, 5);
    dir.position.set(-30, 6, -8);
    this.scene.add(dir);
    // Point 1: 0x1d5e5e, intensity 800, large distance
    const pt1 = new THREE.PointLight(0x1d5e5e, 800, 10000);
    pt1.position.set(-9, 3, -3);
    this.scene.add(pt1);
    // Point 2: 0x1d5e5e, intensity 200
    const pt2 = new THREE.PointLight(0x1d5e5e, 200, 10000);
    pt2.position.set(0, 2, 5);
    this.scene.add(pt2);
  }

  // ==================== 主加载 ====================
  async load() {
    const texKeys = [
      'side', 'ocean', 'arrow', 'pathLine', 'pathLine3', 'flyline6',
      'rotationBorder1', 'rotationBorder2',
      'huiguang', 'particle',
      'focusArrows', 'focusBar', 'focusBg',
      'focusMidQuan', 'focusMoveBg',
      'guangquan01', 'guangquan02',
    ];
    const assets = [
      { name: 'side', type: 'Texture', path: `${TEX}/side.png` },
      { name: 'ocean', type: 'Texture', path: `${TEX}/ocean-bg.png` },
      { name: 'arrow', type: 'Texture', path: `${TEX}/arrow.png` },
      { name: 'pathLine', type: 'Texture', path: `${TEX}/pathLine.png` },
      { name: 'pathLine3', type: 'Texture', path: `${TEX}/pathLine3.png` },
      { name: 'flyline6', type: 'Texture', path: `${TEX}/flyline6.png` },
      { name: 'rotationBorder1', type: 'Texture', path: `${TEX}/rotationBorder1.png` },
      { name: 'rotationBorder2', type: 'Texture', path: `${TEX}/rotationBorder2.png` },
      { name: 'huiguang', type: 'Texture', path: `${TEX}/huiguang.png` },
      { name: 'particle', type: 'Texture', path: `${TEX}/particle.png` },
      { name: 'focusArrows', type: 'Texture', path: `${TEX}/focus/focus_arrows.png` },
      { name: 'focusBar', type: 'Texture', path: `${TEX}/focus/focus_bar.png` },
      { name: 'focusBg', type: 'Texture', path: `${TEX}/focus/focus_bg.png` },
      { name: 'focusMidQuan', type: 'Texture', path: `${TEX}/focus/focus_mid_quan.png` },
      { name: 'focusMoveBg', type: 'Texture', path: `${TEX}/focus/focus_move_bg.png` },
      { name: 'guangquan01', type: 'Texture', path: `${TEX}/guangquan01.png` },
      { name: 'guangquan02', type: 'Texture', path: `${TEX}/guangquan02.png` },
    ];

    const resource = new Resource();
    await resource.loadAll(assets);
    this.textures = {};
    texKeys.forEach(k => { this.textures[k] = resource.getResource(k); });

    // 设置纹理 wrap
    if (this.textures.side) {
      this.textures.side.wrapS = THREE.RepeatWrapping;
      this.textures.side.wrapT = THREE.RepeatWrapping;
      this.textures.side.repeat.set(1, 1.5);
      this.textures.side.offset.y += 0.065;
    }
    if (this.textures.flyline6) {
      this.textures.flyline6.wrapS = THREE.RepeatWrapping;
      this.textures.flyline6.wrapT = THREE.RepeatWrapping;
      this.textures.flyline6.repeat.set(0.5, 2);
    }
    if (this.textures.pathLine) {
      this.textures.pathLine.wrapS = THREE.RepeatWrapping;
      this.textures.pathLine.wrapT = THREE.RepeatWrapping;
      this.textures.pathLine.repeat.set(2, 1);
    }
    if (this.textures.pathLine3) {
      this.textures.pathLine3.wrapS = THREE.RepeatWrapping;
      this.textures.pathLine3.wrapT = THREE.RepeatWrapping;
      this.textures.pathLine3.repeat.set(2, 1);
    }
    if (this.textures.ocean) {
      this.textures.ocean.wrapS = THREE.RepeatWrapping;
      this.textures.ocean.wrapT = THREE.RepeatWrapping;
      this.textures.ocean.colorSpace = THREE.SRGBColorSpace;
    }
    // 加载 GeoJSON
    const [resp, shandongResp] = await Promise.all([
      fetch('js/yantai.json'),
      fetch('js/shandong.json'),
    ]);
    const geojson = await resp.json();
    const shandongGeojson = await shandongResp.json();
    this._shandongFeature = shandongGeojson.features[0];

    // ---- 动态计算投影中心（从 GeoJSON 所有 feature centroid 的包围盒中心） ----
    let minLng = Infinity, maxLng = -Infinity, minLat = Infinity, maxLat = -Infinity;
    (geojson.features || []).forEach(f => {
      const c = f.properties.centroid || f.properties.center;
      if (c && c.length >= 2) {
        minLng = Math.min(minLng, c[0]); maxLng = Math.max(maxLng, c[0]);
        minLat = Math.min(minLat, c[1]); maxLat = Math.max(maxLat, c[1]);
      }
    });
    const centerLng = (minLng + maxLng) / 2;
    const centerLat = (minLat + maxLat) / 2;
    // 更新投影和 geoProject
    this.projection = d3.geoMercator()
      .center([centerLng, centerLat])
      .scale(420)
      .translate([0, 0]);
    this.projectionCenter = [centerLng, centerLat];
    // 保存全市地图参数（点击下钻后返回用）
    this._cityProjectionCenter = [centerLng, centerLat];
    this._cityProjectionScale = 420;
    // 对齐广东：直接返回 Mercator [x, y]，不取反 Y
    this.geoProject = (lngLat) => this.projection(lngLat);
    // 原始全市 GeoJSON（下钻/返回时重建地图用）
    this._yantaiGeojson = geojson;

    this.districtCoords = [];
    maxLat = -Infinity;
    (geojson.features || []).forEach(f => {
      const p = f.properties;
      this.districtCoords.push({
        name: p.name, center: p.center || [], centroid: p.centroid || [],
      });
      if (p.centroid && p.centroid[1] > maxLat) maxLat = p.centroid[1];
    });
    this._northLat = maxLat + 1.125;  // 最北纬度 + 北移偏移（约750px），供焦点标签使用

    // 区县间隔：polygon 向 centroid 微缩 1%
    const spacedGeojson = this._shrinkPolygons(geojson);

    // 按 z-order 创建各层
    this._createBottomBg();
    // this._createShandongOutline();  // 已停用：不再显示山东轮廓
    this._createGrid();
    this._createDiffuse();
    this._createRotateBorders();
    this._createMap3D(spacedGeojson);
    this._createTopFace(spacedGeojson);
    this._createBorderStroke(spacedGeojson);
    this._createFlyLines();
    this._createFocus();
    this._createBars();
    this._createParticles();
    this._createLabels(geojson);  // 标签用原始坐标，不微缩

    // ---- "烟台市" 焦点标签（对齐广东的 "广东省"） ----
    this._createFocusLabel();

    // ---- GSAP 入场动画（对齐 ThreeMaps 广东） ----
    this._setupEntranceAnimation();

    // ---- 区县交互（悬浮高亮 / 点击下钻） ----
    this._initInteraction();

    resource.destroy();
    return this;
  }

  // ==================== 区县间隔：polygon 向 centroid 微缩 ====================
  _shrinkPolygons(geojson) {
    const factor = 0.995;  // 向 centroid 缩小 0.5%（原 1% 造成区县间可见间隙）
    const features = (geojson.features || []).map(f => {
      const centroid = f.properties.centroid;
      if (!centroid || centroid.length < 2) return f;
      const [clng, clat] = centroid;
      // MultiPolygon: coordinates[多边形][环][坐标对]
      const newCoords = f.geometry.coordinates.map(polygons =>
        polygons.map(ring =>
          ring.map(([lng, lat]) => [
            clng + (lng - clng) * factor,
            clat + (lat - clat) * factor,
          ])
        )
      );
      return { ...f, geometry: { ...f.geometry, coordinates: newCoords } };
    });
    return { ...geojson, features };
  }

  // ==================== 底部背景 (对齐 ThreeMaps ocean 纹理) ====================
  _createBottomBg() {
    const tex = this.textures.ocean || this.textures.side;
    const geo = new THREE.PlaneGeometry(20, 20);
    const mat = new THREE.MeshBasicMaterial({
      map: tex,
      color: tex ? 0xffffff : 0x102736,
      transparent: true,
      opacity: 1,
      fog: false,
    });
    const bg = new THREE.Mesh(geo, mat);
    bg.rotation.x = -Math.PI / 2;
    bg.position.set(0, -0.7, 0);
    this.scene.add(bg);
  }

  // ==================== 山东省发光轮廓 (对齐广东 createChinaBlurLine) ====================
  _createShandongOutline() {
    const feature = this._shandongFeature;
    if (!feature) return;

    // Step 1: 提取坐标环
    const allRings = [];
    for (const polygon of feature.geometry.coordinates) {
      for (const ring of polygon) {
        allRings.push(ring);
      }
    }

    // Step 2: 统一用烟台投影 (this.geoProject) — 纹理和 Plane 同一坐标系
    let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
    const projectedRings = allRings.map(ring => {
      return ring.map(([lng, lat]) => {
        const [x, y] = this.geoProject([lng, lat]);
        if (x < minX) minX = x; if (x > maxX) maxX = x;
        if (y < minY) minY = y; if (y > maxY) maxY = y;
        return [x, y];
      });
    });

    // Step 3: Canvas 绘制 — 用烟台投影坐标直接映射到纹理
    const canvasSize = 1024;
    const canvas = document.createElement('canvas');
    canvas.width = canvasSize;
    canvas.height = canvasSize;
    const ctx = canvas.getContext('2d');

    const pad = 0.1;
    const extentW = maxX - minX;
    const extentH = maxY - minY;
    const paddedW = extentW * (1 + pad * 2);
    const paddedH = extentH * (1 + pad * 2);
    const texScale = Math.min(canvasSize / paddedW, canvasSize / paddedH);
    const offsetX = (canvasSize - extentW * texScale) / 2 - minX * texScale;
    const offsetY = (canvasSize - extentH * texScale) / 2 - minY * texScale;

    // Y 轴翻转（Canvas Y 向下，场景 Y 向上）
    const toCanvas = ([x, y]) => [x * texScale + offsetX, canvasSize - (y * texScale + offsetY)];

    ctx.fillStyle = '#ffffff';

    // Pass 1: 发光外圈
    ctx.shadowColor = '#ffffff';
    ctx.shadowBlur = 24;
    for (const ring of projectedRings) {
      ctx.beginPath();
      const [sx, sy] = toCanvas(ring[0]);
      ctx.moveTo(sx, sy);
      for (let i = 1; i < ring.length; i++) {
        const [px, py] = toCanvas(ring[i]);
        ctx.lineTo(px, py);
      }
      ctx.closePath();
      ctx.fill('evenodd');
    }

    // Pass 2: 实心内核
    ctx.shadowBlur = 0;
    for (const ring of projectedRings) {
      ctx.beginPath();
      const [sx, sy] = toCanvas(ring[0]);
      ctx.moveTo(sx, sy);
      for (let i = 1; i < ring.length; i++) {
        const [px, py] = toCanvas(ring[i]);
        ctx.lineTo(px, py);
      }
      ctx.closePath();
      ctx.fill('evenodd');
    }

    // Step 4: CanvasTexture — 对齐广东 NearestFilter + RepeatWrapping
    const texture = new THREE.CanvasTexture(canvas);
    texture.colorSpace = THREE.SRGBColorSpace;
    texture.wrapS = THREE.RepeatWrapping;
    texture.wrapT = THREE.RepeatWrapping;
    texture.generateMipmaps = false;
    texture.minFilter = THREE.NearestFilter;
    texture.magFilter = THREE.NearestFilter;

    // Step 5: PlaneGeometry — 包围盒与纹理完全同源（都是烟台投影），天然对齐
    const sdWidth = paddedW;
    const sdHeight = paddedH;
    const sdCenterX = (minX + maxX) / 2;
    const sdCenterY = (minY + maxY) / 2;

    // 对齐广东 createChinaBlurLine：简单 MeshBasicMaterial，alphaMap + opacity 0.5
    const geo = new THREE.PlaneGeometry(sdWidth, sdHeight);
    const mat = new THREE.MeshBasicMaterial({
      color: 0x3f82cd,
      alphaMap: texture,
      transparent: true,
      opacity: 0.5,
    });

    const mesh = new THREE.Mesh(geo, mat);
    mesh.rotateX(-Math.PI / 2);

    // ---- 山东省轮廓：统一大小 + 对齐烟台 3D 地图（烟台地图代码零改动）----
    // 1) 统一大小：山东宽度缩放到与烟台 3D 地图宽度一致（保持宽高比）
    //    烟台投影包围盒实测 17.42 宽，山东 Plane（含10%pad）69.45 宽 → S≈0.25
    var ytW = 180;               // 烟台 3D 地图投影包围盒宽度（实测）
    var S = ytW / sdWidth;         // 山东缩放到与烟台地图同宽
    mesh.scale.set(S, S, S);       // 绕 Plane 中心缩放

    // 2) 锚点：莱山区（与 _createFocus 光柱同一坐标 [121.44, 37.51]）
    //    光柱经 mapGroup.rotateX(-PI/2) 后的世界坐标 = (geoProject[0], geoProject[1])
    var yantaiProj = this.geoProject([121.44, 37.51]);
    var yantaiPX = yantaiProj[0];
    var yantaiPY = yantaiProj[1];

    // 3) 锚点相对山东 Plane 中心的偏移（缩放后 = 原偏移 * S）
    var dX = (yantaiPX - sdCenterX) * S;
    var dY = (yantaiPY - sdCenterY) * S;

    // 4) 目标：山东的莱山点对齐到莱山光柱正下方
    var targetX = yantaiPX + 0;   // 莱山光柱 worldX（改最后的 +0 微调左右）
    var targetZ = yantaiPY + 0;   // 莱山光柱 worldZ（改最后的 +0 微调前后）
    var yPos = -0.5;              // Y 层级（地图下方）

    // 经 rotateX(-PI/2)：worldX = posX + dX, worldZ = posZ - dY
    mesh.position.set(targetX - dX, yPos, targetZ + dY);
    mesh.renderOrder = -5;
    this.scene.add(mesh);
  }

  // ==================== 网格背景 (对齐 ThreeMaps 参数) ====================
  _createGrid() {
    const grid = new Grid(this.scene, { on: () => {}, off: () => {}, emit: () => {} }, {
      gridSize: 50,
      gridDivision: 20,
      gridColor: 0x1b4b70,
      shapeSize: 0.5,
      shapeColor: 0x2a5f8a,
      pointSize: 0.1,
      pointColor: 0x154d7d,
    });
    // Grid 直接留在 scene 中（水平 XZ 平面），对齐 ThreeMaps
    grid.instance.renderOrder = -10;
    this.gridInstance = grid;
  }

  // ==================== 扩散波纹 (对齐 ThreeMaps) ====================
  _createDiffuse() {
    const geometry = new THREE.PlaneGeometry(200, 200);
    const material = new THREE.MeshBasicMaterial({
      color: 0x000000,
      depthWrite: false,
      transparent: true,
      blending: THREE.CustomBlending,
    });
    material.blendEquation = THREE.AddEquation;
    material.blendSrc = THREE.DstColorFactor;
    material.blendDst = THREE.OneFactor;

    this.diffuseMesh = new THREE.Mesh(geometry, material);
    this.diffuseMesh.rotation.x = -Math.PI / 2;
    this.diffuseMesh.position.set(0, 0.21, 0);
    this.diffuseMesh.renderOrder = 3;
    this.scene.add(this.diffuseMesh);
    // 波纹最大半径 size: 60,diffuseSpeed: 8.0,
    this.diffuseShader = new DiffuseShader({
      material,
      size: 45,
      diffuseColor: 0x71918e,
      diffuseSpeed: 8.0,
      diffuseWidth: 2.0,
      time: { on: () => {}, off: () => {}, emit: () => {} },
      callback: () => {},
    });

    this._diffuseTime = 0;
  }

  // ==================== 旋转圆环 (对齐 ThreeMaps) ====================
  _createRotateBorders() {
    const mat1 = new THREE.MeshBasicMaterial({
      map: this.textures.rotationBorder1,
      color: 0x48afff,
      transparent: true,
      opacity: 0.2,
      side: THREE.DoubleSide,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
    });
    // width: 32.0,  外圈
    const plane1 = new Plane({ on: () => {}, off: () => {}, emit: () => {} }, {
      width: 24.0,  // 对齐烟台 scale 600 的地图范围
      needRotate: true,
      rotateSpeed: 0.001,
      material: mat1,
    });
    plane1.instance.rotation.x = -Math.PI / 2;
    plane1.instance.renderOrder = 6;
    plane1.instance.scale.set(0, 0, 0);
    plane1.setParent(this.scene);
    plane1.instance.position.set(0, 0.28, 0);
    this.rotatePlane1 = plane1;

    const mat2 = new THREE.MeshBasicMaterial({
      map: this.textures.rotationBorder2,
      color: 0x48afff,
      transparent: true,
      opacity: 0.4,
      side: THREE.DoubleSide,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
    });
    // width: 30.0, 内圈
    const plane2 = new Plane({ on: () => {}, off: () => {}, emit: () => {} }, {
      width: 22.0,  // 对齐烟台 scale 600 的地图范围
      needRotate: true,
      rotateSpeed: -0.004,
      material: mat2,
    });
    plane2.instance.rotation.x = -Math.PI / 2;
    plane2.instance.renderOrder = 6;
    plane2.instance.scale.set(0, 0, 0);
    plane2.setParent(this.scene);
    plane2.instance.position.set(0, 0.3, 0);
    this.rotatePlane2 = plane2;
  }

  // ==================== 3D 挤出地图 (对齐 ThreeMaps) ====================
  _createMap3D(geojson) {
    // 侧面材质 — MeshStandardMaterial, shader 染色 0x2a6e92
    const sideMap = this.textures.side;
    this.sideMaterial = new THREE.MeshStandardMaterial({
      color: 0xffffff,
      map: sideMap,
      fog: false,
      transparent: true,
      opacity: 1,
      side: THREE.DoubleSide,
    });
    this.sideMaterial.onBeforeCompile = (shader) => {
      shader.uniforms = {
        ...shader.uniforms,
        uColor1: { value: new THREE.Color(0x2a6e92) },
        uColor2: { value: new THREE.Color(0x2a6e92) },
      };
      shader.vertexShader = shader.vertexShader.replace(
        'void main() {',
        `varying vec3 vPosition;
        void main() {
          vPosition = position;
        `
      );
      shader.fragmentShader = shader.fragmentShader.replace(
        'void main() {',
        `varying vec3 vPosition;
        uniform vec3 uColor1;
        uniform vec3 uColor2;
        void main() {
        `
      );
      shader.fragmentShader = shader.fragmentShader.replace(
        '#include <opaque_fragment>',
        `#ifdef OPAQUE
        diffuseColor.a = 1.0;
        #endif
        #ifdef USE_TRANSMISSION
        diffuseColor.a *= transmissionAlpha + 0.1;
        #endif
        vec3 gradient = mix(uColor1, uColor2, vPosition.z/1.2);
        outgoingLight = outgoingLight*gradient;
        gl_FragColor = vec4( outgoingLight, diffuseColor.a );`
      );
    };

    // 顶面材质 — MeshLambertMaterial, shader 染色 0x2a6e92→0x102736
    const topMat = new THREE.MeshLambertMaterial({
      color: 0xffffff,
      transparent: true,
      opacity: 1,
      fog: false,
      side: THREE.DoubleSide,
    });
    this._topMat = topMat;  // 供下钻重建复用
    topMat.onBeforeCompile = (shader) => {
      shader.uniforms = {
        ...shader.uniforms,
        uColor1: { value: new THREE.Color(0x2a6e92) },
        uColor2: { value: new THREE.Color(0x102736) },
      };
      shader.vertexShader = shader.vertexShader.replace(
        'void main() {',
        `varying vec3 vPosition;
        void main() {
          vPosition = position;
        `
      );
      shader.fragmentShader = shader.fragmentShader.replace(
        'void main() {',
        `varying vec3 vPosition;
        uniform vec3 uColor1;
        uniform vec3 uColor2;
        void main() {
        `
      );
      shader.fragmentShader = shader.fragmentShader.replace(
        '#include <opaque_fragment>',
        `#ifdef OPAQUE
        diffuseColor.a = 1.0;
        #endif
        #ifdef USE_TRANSMISSION
        diffuseColor.a *= transmissionAlpha + 0.1;
        #endif
        vec3 gradient = mix(uColor1, uColor2, vPosition.x/15.78);
        outgoingLight = outgoingLight*gradient;
        float topAlpha = 0.5;
        if(vPosition.z>0.3){
          diffuseColor.a *= topAlpha;
        }
        gl_FragColor = vec4( outgoingLight, diffuseColor.a );`
      );
    };

    // focusMapGroup 包装层（对齐 ThreeMaps 入场动画结构）
    this.focusMapGroup = new THREE.Group();
    this.focusMapGroup.position.set(0, 0, -0.01);
    this.focusMapGroup.scale.set(1, 1, 1);
    this.mapGroup.add(this.focusMapGroup);

    const extrude = new ExtrudeMap(this.geoProject, {
      data: geojson,
      depth: this.depth,
      topFaceMaterial: topMat,
      sideMaterial: this.sideMaterial,
      position: new THREE.Vector3(0, 0, 0.11),
      renderOrder: 9,
    });
    extrude.setParent(this.focusMapGroup);
    this.extrudeMap = extrude;
    this.coordinates = extrude.getCoordinates();
  }

  // ==================== 顶面渐变覆盖 (对齐 ThreeMaps) ====================
  _createTopFace(geojson) {
    const faceMat = new THREE.MeshStandardMaterial({
      color: 0xffffff,
      transparent: true,
      opacity: 0.5,
      fog: false,
    });
    this._faceMat = faceMat;  // 供下钻重建 / 悬浮高亮复用
    new GradientShader(faceMat, {
      uColor1: 0x12bbe0,
      uColor2: 0x0094b5,
      size: 15.0,
      dir: 'x',
    });

    const baseMap = new BaseMap(this.geoProject, {
      data: geojson,
      merge: false,
      material: faceMat,
      position: new THREE.Vector3(0, 0, this.depth + 0.22),
      renderOrder: 2,
    });
    baseMap.setParent(this.focusMapGroup);
    this.baseMap = baseMap;

    // 收集交互面
    baseMap.mapGroup.traverse((child) => {
      if (child.isMesh) {
        child.userData.isMapFace = true;
        this.intersectMeshes.push(child);
      }
    });
  }

  // ==================== 轮廓流光描边 (对齐 ThreeMaps) ====================
  _createBorderStroke(geojson) {
    const strokeTex = this.textures.pathLine3 || this.textures.pathLine;
    this.strokeMaterial = new THREE.MeshBasicMaterial({
      color: 0x2bc4dc,
      map: strokeTex,
      alphaMap: strokeTex,
      fog: false,
      transparent: true,
      opacity: 1,
      blending: THREE.AdditiveBlending,
    });
    this._strokeMat = this.strokeMaterial;  // 供下钻重建 / 悬浮高亮复用

    const line = new Line(this.geoProject, {
      data: geojson,
      type: 'Line3',
      material: this.strokeMaterial,
      tubeRadius: 0.06,  // 区县分隔线（原 0.1 太粗影响美观）
      position: new THREE.Vector3(0, 0, this.depth + 0.24),
      renderOrder: 22,
    });
    line.setParent(this.focusMapGroup);
    this.borderLine = line;
  }

  // ==================== 飞线 (对齐 ThreeMaps) ====================
  _createFlyLines() {
    // 飞线中心 = 莱山区
    const center = [121.44, 37.51];
    const flyData = this.districtCoords
      .filter(d => d.centroid && d.centroid.length === 2)
      .map(d => ({ centroid: d.centroid }));

    const flyTex = this.textures.flyline6;
    const flyMaterial = new THREE.MeshBasicMaterial({
      map: flyTex,
      color: 0x2a6f72,
      transparent: true,
      fog: false,
      opacity: 1,
      depthTest: false,
      blending: THREE.AdditiveBlending,
    });

    const flyLine = new FlyLine(
      this._fakeTime,
      this.geoProject,
      {
        centerPoint: center,
        middleHeight: 3,
        speed: 0.006,
        texture: flyTex,
        radius: 0.1,
        segments: 32,
        radialSegments: 2,
        data: flyData,
        material: flyMaterial,
      }
    );
    flyLine.instance.position.z = this.depth + 0.44;
    flyLine.setParent(this.mapGroup);
    this.flyLine = flyLine;
  }

  // ==================== 聚焦光圈 (对齐 ThreeMaps) ====================
  _createFocus() {
    // 莱山区坐标 [121.44, 37.51]
    const [cx, cy] = this.geoProject([121.44, 37.51]);
    const focus = new Focus({
      focusArrows: this.textures.focusArrows,
      focusBar: this.textures.focusBar,
      focusBg: this.textures.focusBg,
      focusMidQuan: this.textures.focusMidQuan,
      focusMoveBg: this.textures.focusMoveBg,
    }, { color1: 0xbdfdfd, color2: 0xbdfdfd });
    focus.position.set(cx, -cy, this.depth + 0.44);
    this.mapGroup.add(focus);
    this.focus = focus;
  }

  // ==================== 3D 柱状图 (对齐 ThreeMaps) ====================
  // rankingOverride（可选）：周期切换时传入按周期重算的区县排名；不传用导出静态数据
  _createBars(rankingOverride) {
    this.barGroup = new THREE.Group();
    // 柱状图标签组 (对齐广东 labelGroup) — mapGroup 已旋转，此处不再重复旋转
    this.barLabelGroup = new THREE.Group();
    this.allBarLabels = [];

    const data = window.DASHBOARD_DATA || {};
    // 全部有数据的区县都出柱（不再截前 7：芝罘/牟平/招远/蓬莱等排名靠后的区县也要有柱）
    const ranking = rankingOverride || data.district_ranking || [];

    const factor = 0.55;                 // 整体矮一点：14 根柱互不遮挡、不压区县面
    const maxHeight = 4.0 * factor;
    const barSize = 0.1 * factor;
    const minBarH = maxHeight * 0.12;    // 最少可见柱高：项目少的区县（1~2 条）也有可观察的柱
    const maxVal = ranking.length > 0 ? Math.max(...ranking.map(r => r.value)) : 1;

    this.allBars = [];
    this.allBarMaterials = [];

    ranking.forEach((item, idx) => {
      let coord = this.districtCoords.find(d => d.name === item.name);
      // 无 geoJson 几何的区县（高新区/开发区等）：用 DISTRICT_CENTERS 中心点兜底 → 有数据就有柱
      if (!coord || !coord.centroid || coord.centroid.length < 2) {
        const dc = window.DISTRICT_CENTERS && window.DISTRICT_CENTERS[item.name];
        if (!dc || dc.length < 2) return;
        coord = { name: item.name, centroid: dc };
      }

      const [bx, by] = this.geoProject(coord.centroid);
      // 幂 0.6 比例：104→满高、20→0.75、10→0.48、5→0.34、1→0.13（再套最小柱高 0.26）
      // 每差 10 条高度差距明显（柱顶标签随柱高上下错开，市中心密集区县不再重叠）
      const geoHeight = Math.max(minBarH, maxHeight * Math.pow(item.value / maxVal, 0.6));

      // 柱体材质 — GradientShader 垂直渐变（统一黄色渐变）
      const barMat = new THREE.MeshBasicMaterial({
        color: 0xffffff,
        transparent: true,
        opacity: 1,
        depthTest: false,
        fog: false,
      });
      new GradientShader(barMat, {
        uColor1: 0xfedb32,
        uColor2: 0xfff7b0,
        size: geoHeight,
        dir: 'y',
      });

      const geo = new THREE.BoxGeometry(barSize, barSize, geoHeight);
      geo.translate(0, 0, geoHeight / 2);
      const box = new THREE.Mesh(geo, barMat);
      box.renderOrder = 5;
      box.position.set(bx, -by, this.depth + 0.45);
      box.userData = { name: item.name, isBar: true };
      this.intersectMeshes.push(box);
      this.allBars.push(box);
      this.allBarMaterials.push(barMat);
      this.barGroup.add(box);

      // 光辉 (huiguang) — 3 个交叉面
      if (this.textures.huiguang) {
        const hgColor = 0xfff6a0;
        const hgGeo = new THREE.PlaneGeometry(0.35, geoHeight);
        hgGeo.translate(0, geoHeight / 2, 0);
        const hgTex = this.textures.huiguang;
        hgTex.colorSpace = THREE.SRGBColorSpace;
        hgTex.wrapS = THREE.RepeatWrapping;
        hgTex.wrapT = THREE.RepeatWrapping;
        const hgMat = new THREE.MeshBasicMaterial({
          color: hgColor,
          map: hgTex,
          transparent: true,
          opacity: 0.4,
          depthWrite: false,
          side: THREE.DoubleSide,
          blending: THREE.AdditiveBlending,
        });
        const hg1 = new THREE.Mesh(hgGeo, hgMat);
        hg1.renderOrder = 10;
        hg1.rotateX(Math.PI / 2);
        const hg2 = hg1.clone();
        hg2.rotateY((Math.PI / 180) * 60);
        const hg3 = hg1.clone();
        hg3.rotateY((Math.PI / 180) * 120);
        box.add(hg1);
        box.add(hg2);
        box.add(hg3);
      }

      // 底部旋转光环 (对齐广东 createQuan) — 莱山区底座更大
      const isLaiShan = item.name === '莱山区';
      const quanSize = isLaiShan ? 0.7 : 0.35;
      const quans = this._createQuan(new THREE.Vector3(0, 0, 0), quanSize);
      if (quans && quans.length) {
        box.add(...quans);
        // 保存引用，GSAP 入场动画需要缩放
        if (!this._allQuans) this._allQuans = [];
        this._allQuans.push(...quans);
      }

      // CSS3D 标签 (对齐广东 bar label — 大号数字 + 名称/拼音 + 霓虹排名)
      if (this.label3d) {
        const pinYinMap = {
          '芝罘区':'Zhifu','莱阳市':'Laiyang','龙口市':'Longkou',
          '牟平区':'Muping','莱州市':'Laizhou','海阳市':'Haiyang',
          '莱山区':'Laishan','福山区':'Fushan','蓬莱区':'Penglai',
          '招远市':'Zhaoyuan','栖霞市':'Qixia','烟台开发区':'YEDA',
          '烟台高新区':'YT-HiTech','长岛综试区':'Changdao',
        };
        const en = pinYinMap[item.name] || item.name;
        const label = this.label3d.create('', 'bar-label', false);
        label.init(
          `<div class="bar-label-wrap">
            <div class="bar-label-num">
              <span class="bar-label-val">${item.value}</span>
              <span class="bar-label-unit">个项目</span>
            </div>
            <div class="bar-label-info">
              <span class="bar-label-name">${item.name}</span>
              <span class="bar-label-en">${en}</span>
            </div>
          </div>`,
          new THREE.Vector3(bx, -by, this.depth + 0.65 + geoHeight)
        );
        this.label3d.setLabelStyle(label, 0.01, 'x');
        label.setParent(this.barLabelGroup);
        this.allBarLabels.push(label);
      }
    });

    this.mapGroup.add(this.barGroup);
    this.mapGroup.add(this.barLabelGroup);
  }

  // 周期切换：更新现有柱（柱高/柱顶数字/可见性），不重建 CSS3D 标签——
  // 重建会触发 CSS3DRenderer 视锥剔除间歇性把标签置 hidden（"标签有时没有有时出现"）
  updateBars(ranking) {
    if (!this.allBars || !this.allBars.length) { this.replaceBars(ranking); return; }
    const maxVal = ranking.length ? Math.max(...ranking.map(r => r.value)) : 1;
    const factor = 0.55, maxHeight = 4.0 * factor, minBarH = maxHeight * 0.12;
    const names = new Set(ranking.map(r => r.name));
    this.allBars.forEach((box, i) => {
      const label = this.allBarLabels[i];
      const inRank = names.has(box.userData.name);
      box.visible = inRank;
      if (label) {
        if (inRank) {
          const item = ranking.find(r => r.name === box.userData.name);
          const geoHeight = Math.max(minBarH, maxHeight * Math.pow(item.value / maxVal, 0.6));
          // 更新柱几何（高度）
          box.geometry.dispose();
          const geo = new THREE.BoxGeometry(0.055, 0.055, geoHeight);
          geo.translate(0, 0, geoHeight / 2);
          box.geometry = geo;
          // 更新光辉面高度（box 子网格中：光辉是 PlaneGeometry(0.35, h) 宽高不等；
          // 旋转光环是正方形 width===height，不能动——否则圆形光环被压成长条）
          box.children.forEach(ch => {
            const gp = ch.geometry && ch.geometry.parameters;
            if (gp && gp.width !== undefined && gp.height !== undefined && gp.width !== gp.height) {
              ch.geometry.dispose();
              const hg = new THREE.PlaneGeometry(0.35, geoHeight);
              hg.translate(0, geoHeight / 2, 0);
              ch.geometry = hg;
            }
          });
          // 更新标签数字
          try {
            const valEl = label.element.querySelector('.bar-label-val');
            if (valEl) valEl.textContent = item.value;
          } catch (e) {}
          // 柱形图动画：柱子从底部生长（geometry 底部 z=0，scale.z 即从底部长高）
          // + 标签跟随柱顶同步上升；周期切换/初始加载都生效
          const growDelay = i * 0.04;
          box.scale.z = 0.01;
          if (typeof gsap !== 'undefined') {
            gsap.killTweensOf(box.scale);
            gsap.to(box.scale, { z: 1, duration: 0.55, ease: 'power2.out', delay: growDelay });
            gsap.killTweensOf(label.position);
            gsap.to(label.position, {
              z: this.depth + 0.65 + geoHeight, duration: 0.55, ease: 'power2.out', delay: growDelay,
            });
          } else {
            box.scale.z = 1;
            label.position.z = this.depth + 0.65 + geoHeight;
          }
          // 标签显隐由 setMapMode 统一控制：仅柱状图模式显示（预警图/热力图模式不 show，
          // 否则切到预警图后柱状图标签残留 → 标签和图钉混乱）
          if (this._mapMode === 'bar' && label.show) label.show();
        } else {
          if (label.hide) label.hide();
        }
      }
    });
  }

  // 周期切换：重建柱状图（清理旧柱+标签 → 用新 ranking 重绘）
  replaceBars(ranking) {
    if (!this.barGroup) return;
    const wasVisible = this.barGroup.visible;
    const wasLabelVisible = this.barLabelGroup ? this.barLabelGroup.visible : true;
    // 清理旧柱与材质 + 从射线检测列表移除旧柱
    this.allBars.forEach(b => { this.barGroup.remove(b); });
    if (this.intersectMeshes) {
      this.intersectMeshes = this.intersectMeshes.filter(m => !(m && m.userData && m.userData.isBar));
    }
    this.allBarMaterials.forEach(m => { if (m && m.dispose) m.dispose(); });
    this.allBars = [];
    this.allBarMaterials = [];
    // 清理旧 CSS3D 标签：element 是 CSS3DObject 的 DOM 节点（挂在 CSS3DRenderer 渲染层），
    // 必须从 DOM 移除，否则旧标签残留在渲染层盖住新标签（柱顶数字消失的根因）
    this.allBarLabels.forEach(l => {
      try { if (l && l.element && l.element.parentNode) l.element.parentNode.removeChild(l.element); } catch (e) {}
    });
    this.allBarLabels = [];
    if (this.barLabelGroup) this.barLabelGroup.clear();
    // 重建（沿用当前可见性）
    this.mapGroup.remove(this.barGroup);
    this.mapGroup.remove(this.barLabelGroup);
    try {
      this._createBars(ranking);
    } catch (e) {
      console.error('[replaceBars] 重建柱状图失败:', e);
    }
    if (this.barGroup) this.barGroup.visible = wasVisible !== false;
    if (this.barLabelGroup) this.barLabelGroup.visible = wasLabelVisible !== false;
  }

  // ==================== 柱状图底部旋转光环 (对齐广东 createQuan) ====================
  _createQuan(position, size = 0.5) {
    const gq1 = this.textures.guangquan01;
    const gq2 = this.textures.guangquan02;
    if (!gq1 || !gq2) return new THREE.Group();

    const geo = new THREE.PlaneGeometry(size, size);
    const mat1 = new THREE.MeshBasicMaterial({
      color: 0xffffff,
      map: gq1,
      alphaMap: gq1,
      opacity: 1,
      transparent: true,
      depthTest: false,
      fog: false,
      blending: THREE.AdditiveBlending,
    });
    const mat2 = new THREE.MeshBasicMaterial({
      color: 0xffffff,
      map: gq2,
      alphaMap: gq2,
      opacity: 1,
      transparent: true,
      depthTest: false,
      fog: false,
      blending: THREE.AdditiveBlending,
    });

    const mesh1 = new THREE.Mesh(geo, mat1);
    const mesh2 = new THREE.Mesh(geo, mat2);
    mesh1.renderOrder = 6;
    mesh2.renderOrder = 6;
    // mapGroup 空间 Z=高度，PlaneGeometry 默认面朝 +Z，正好平躺在地图表面
    // 不需要 rotateX，否则光环竖立起来从上方看不到
    mesh1.position.copy(position);
    mesh2.position.copy(position);
    mesh2.position.z -= 0.001;
    // 初始缩放为 0，入场动画展开
    mesh1.scale.set(0, 0, 0);
    mesh2.scale.set(0, 0, 0);

    // 持续旋转
    this._tickCallbacks.push(() => {
      mesh1.rotation.z += 0.05;
    });

    return [mesh1, mesh2];
  }

  // ==================== 粒子系统 (对齐 ThreeMaps) ====================
  _createParticles() {
    const pMat = new THREE.PointsMaterial({
      map: Particles.createTexture(),
      size: 1,
      color: 0x00eeee,
      transparent: true,
      opacity: 1,
      depthTest: false,
      depthWrite: false,
      vertexColors: true,
      blending: THREE.AdditiveBlending,
      sizeAttenuation: true,
    });

    const particles = new Particles(this._fakeTime, {
      num: 10,
      range: 30,
      dir: 'up',
      speed: 0.05,
      renderOrder: 99,
      material: pMat,
    });
    this.particleGroup = new THREE.Group();
    this.scene.add(this.particleGroup);
    this.particleGroup.rotation.x = -Math.PI / 2;
    this.particleGroup.position.set(0, 0, 0);
    particles.setParent(this.particleGroup);
    this.particles = particles;
  }

  // ==================== CSS3D 标签 ====================
  _createLabels(geojson) {
    this._districtLabels = [];
    // 标签统一挂到独立组，下钻时整组隐藏
    this._districtLabelGroup = new THREE.Group();
    this.mapGroup.add(this._districtLabelGroup);
    (geojson.features || []).forEach(f => {
      const { name, centroid } = f.properties;
      if (!centroid || centroid.length < 2) return;
      const [lx, ly] = this.geoProject(centroid);
      const label = this.label3d.create(
        `<div class="map-label">${name}</div>`,
        'map-label', false
      );
      label.position.set(lx, -ly, 0.4);
      this.label3d.setLabelStyle(label, 0.07, 'x', Math.PI / 2, 'none');
      label.setParent(this._districtLabelGroup);
      this._districtLabels.push(label);
    });
  }

  // ==================== 焦点标签 "烟台市" (对齐广东 "广东省") ====================
  _createFocusLabel() {
    if (!this.label3d || !this.projectionCenter) return;
    // 标签位置：正北边，最北区县上方
    const labelCenter = [this.projectionCenter[0], this._northLat || this.projectionCenter[1]];
    const [lx, ly] = this.geoProject(labelCenter);
    const label = this.label3d.create('', 'map-focus-label', false);
    label.init(
      `<div class="focus-label-wrap"><span class="focus-label-zh">烟台市</span><span class="focus-label-en">YANTAI CITY</span></div>`,
      new THREE.Vector3(lx, -ly, 0.4)
    );
    this.label3d.setLabelStyle(label, 0.015, 'x');
    // 焦点标签添加到 mapGroup（跟随地图旋转）
    label.setParent(this.mapGroup);
    this._focusLabel = label;
  }

  // ==================== GSAP 入场动画 (对齐 ThreeMaps 广东) ====================
  _setupEntranceAnimation() {
    // 初始状态：地图平面（Z 缩放到 0），侧面不可见
    if (this.focusMapGroup) {
      this.focusMapGroup.scale.set(1, 1, 0);
    }
    // 初始隐藏非地图元素
    const initOpacity = (mat) => { if (mat) { mat.transparent = true; mat.opacity = 0; } };
    initOpacity(this.sideMaterial);

    const tl = gsap.timeline({ paused: true });
    this._entranceTl = tl;

    // 阶段 1: 相机从侧面旋转到正面
    tl.to(this.camera.position, {
      duration: 2,
      x: -0.17,
      y: 9.68,
      z: 20.688611202093714,
      ease: 'circ.out',
    }, 0);

    // 阶段 2: 地图 Z 轴"生长"（从扁平到立体）
    if (this.focusMapGroup) {
      tl.to(this.focusMapGroup.scale, {
        duration: 1,
        x: 1, y: 1, z: 1,
        ease: 'circ.out',
      }, 0.5);
    }

    // 阶段 3: 侧面材质淡入
    if (this.sideMaterial) {
      tl.to(this.sideMaterial, {
        duration: 1,
        opacity: 1,
        ease: 'circ.out',
        onComplete: () => {
          this.sideMaterial.transparent = false;
          this.sideMaterial.needsUpdate = true;
        },
      }, 0.5);
    }

    // 圆环缩放
    if (this.rotatePlane1 && this.rotatePlane1.instance) {
      tl.fromTo(this.rotatePlane1.instance.scale, { x: 0, y: 0, z: 0 }, {
        duration: 1, x: 1, y: 1, z: 1, ease: 'circ.out',
      }, 1);
    }
    if (this.rotatePlane2 && this.rotatePlane2.instance) {
      tl.fromTo(this.rotatePlane2.instance.scale, { x: 0, y: 0, z: 0 }, {
        duration: 1, x: 1, y: 1, z: 1, ease: 'circ.out',
      }, 1.2);
    }

    // 柱状图底部光环缩放 (对齐广东 createQuan 入场)
    if (this._allQuans && this._allQuans.length) {
      this._allQuans.forEach((q, i) => {
        tl.fromTo(q.scale, { x: 0, y: 0, z: 0 }, {
          duration: 0.5, x: 1, y: 1, z: 1, ease: 'circ.out',
        }, 1.4 + i * 0.03);
      });
    }

    // 柱状图标签入场 — 从右下滑入 + 淡入 (对齐广东 bar label 动画)
    if (this.allBarLabels && this.allBarLabels.length) {
      this.allBarLabels.forEach((label, i) => {
        const wrap = label.element.querySelector('.bar-label-wrap');
        if (wrap) {
          tl.to(wrap, {
            duration: 0.6,
            x: '0%',
            y: '0%',
            opacity: 1,
            ease: 'circ.out',
          }, 1.4 + i * 0.12);
        }
      });
    }

    // 启动动画
    tl.play();
  }

  // ==================== 添加散点（Sprite 纹理，对齐 ThreeMaps） ====================
  addScatter(lng, lat, priority, color, name, data) {
    const [sx, sy] = this.geoProject([lng, lat]);
    const group = new THREE.Group();
    group.position.set(sx, -sy, this.depth + 0.45);

    // 对齐广东：使用 arrow 纹理 + SpriteMaterial（不加 AdditiveBlending，避免光污染）
    const arrowTex = this.textures.arrow;
    const tintColor = color === 0xff4444 ? 0xff6666 : 0xffdd66;
    const spriteMat = new THREE.SpriteMaterial({
      map: arrowTex || undefined,
      color: arrowTex ? 0xffffff : tintColor,
      fog: false,
      transparent: true,
      depthTest: false,
    });
    const sprite = new THREE.Sprite(spriteMat);
    sprite.renderOrder = 23;
    const baseScale = 0.08 + priority * 0.06;  // 对齐广东 0.1~0.3 范围
    sprite.scale.set(baseScale, baseScale, 1);
    group.add(sprite);

    group.userData = { name, priority, color, baseScale, sprite, data };
    this.mapGroup.add(group);
    this.scatterItems.push(group);
    return group;
  }

  // ==================== 预警图模式：3D 图钉（倒水滴+发光+地面光圈+胶囊标签） ====================
  // 底座贴地图表面（街道层 z=0.83，视觉接触不悬空）；保存原始位置供下钻缩放
  _createWarningPinShape() {
    if (this._sharedPinGeo) return this._sharedPinGeo;
    const shape = new THREE.Shape();
    shape.moveTo(0, 0);
    shape.bezierCurveTo(-0.55, 0.9, -1.0, 1.7, -1.0, 2.4);
    shape.absarc(0, 2.4, 1.0, Math.PI, 0, true);
    shape.bezierCurveTo(1.0, 1.7, 0.55, 0.9, 0, 0);
    const hole = new THREE.Path();
    hole.absarc(0, 2.4, 0.35, 0, Math.PI * 2, true);
    shape.holes.push(hole);
    const geo = new THREE.ExtrudeGeometry(shape, {
      depth: 0.3, bevelEnabled: true, bevelSegments: 4, steps: 1,
      bevelSize: 0.06, bevelThickness: 0.06,
    });
    geo.rotateX(Math.PI / 2);      // 形状高度 → +Z（地图上方）
    const s = (this._pinConfig && this._pinConfig.pinScale) || 0.45;
    geo.scale(s, s, s);            // 适配地图尺度（高度≈s×2.4）
    geo.computeBoundingBox();
    geo.translate(0, 0, -geo.boundingBox.min.z);  // 底部贴 z=0
    this._sharedPinGeo = geo;
    return geo;
  }

  _addWarningPins() {
    if (this._warningPinGroup) return;
    const group = new THREE.Group();
    const baseGeo = this._createWarningPinShape();
    const data = window.DASHBOARD_DATA || {};
    let pts = (data.map_points || []).slice();   // let：同名去重会重新赋值
    // 图钉太多：按 priority（value[2]）降序只取前 maxPins，同坐标折叠/下钻展开仍基于该子集
    const maxPins = (this._pinConfig && this._pinConfig.maxPins) || 0;
    pts.sort((a, b) => ((b.value && b.value[2]) || b.priority || 0) - ((a.value && a.value[2]) || a.priority || 0));
    // 全量创建（下钻要显示区县全部点，不做截断/去重）；
    // 全市态显示由 _foldDuplicatePins 统一控制：同坐标折叠 + 同名折叠 + 只显示前 maxPins（isTop）
    const topCount = maxPins > 0 ? Math.min(maxPins, pts.length) : pts.length;
    // 近坐标散开：同 0.0001° 归为一组（key 与 _dupGroups 一致），组内只有 priority 最高的"代表"参与散开，
    // 其余保持原位（_foldDuplicatePins 会折叠隐藏，下钻展开时位置与原始一致，不会重复/错位）。
    // 间距 MIN_GAP=0.012（约 1.2km）轻微散开防重叠，最大偏移 2 圈（约 2.4km）保位置不失真；
    // 只影响 3D 显示位置，data.value 不动 → 2D 地图/下钻/详情始终精确
    const MIN_GAP = 0.012;
    const coordGroups = new Map();
    pts.forEach((p, i) => {
      const v = p.value;
      if (!v || v.length < 2) return;
      const key = Math.round(v[0] * 1e4) + ',' + Math.round(v[1] * 1e4);
      if (!coordGroups.has(key)) coordGroups.set(key, []);
      coordGroups.get(key).push(i);
    });
    // 近似同名组键分配（与 2D 同规则：前缀且长度差≥2 → 同一项目，如"基地项目"vs"基地项目车间"）
    const nameKeys = [];
    const groupAssign = pts.map(p => {
      const nm = (p.name || '').trim();
      if (!nm) return '';
      for (let i = 0; i < nameKeys.length; i++) {
        if (this._nameSimilar(nm, nameKeys[i])) return nameKeys[i];
      }
      nameKeys.push(nm);
      return nm;
    });
    const usedPos = [];
    const spreadPos = pts.map((p, i) => {
      const v = p.value;
      if (!v || v.length < 2) return null;
      const key = Math.round(v[0] * 1e4) + ',' + Math.round(v[1] * 1e4);
      const grp = coordGroups.get(key) || [i];
      if (grp[0] !== i) return [v[0], v[1]];   // 非组代表：原位不动（折叠隐藏）
      let lng = v[0], lat = v[1];
      for (let r = 1; r <= 2; r++) {   // 组代表：参与散开；最大偏移 2×MIN_GAP ≈ 2.4km
        const ang = i * 2.39996 + r * 0.6;   // 黄金角混合，方向分散
        const tl = lng + Math.cos(ang) * MIN_GAP * r;
        const ta = lat + Math.sin(ang) * MIN_GAP * r;
        if (!usedPos.some(u => Math.hypot(u[0] - tl, u[1] - ta) < MIN_GAP)) { lng = tl; lat = ta; break; }
      }
      usedPos.push([lng, lat]);
      return [lng, lat];
    });
    // 同坐标（0.0001° 内）的多个项目：全市态只显示一个（优先级最高），下钻时展开全部
    this._dupGroups = new Map();
    pts.forEach((p, pi) => {
      const v = p.value;
      if (!v || v.length < 2) return;
      const key = Math.round(v[0] * 1e4) + ',' + Math.round(v[1] * 1e4);
      if (!this._dupGroups.has(key)) this._dupGroups.set(key, []);
      const sp = spreadPos[pi] || [v[0], v[1]];   // 散开后的显示坐标（数据坐标不动）
      const [sx, sy] = this.geoProject([sp[0], sp[1]]);
      const [tx, ty] = this.geoProject([v[0], v[1]]);   // 真实世界坐标（下钻/定位用，不受散开影响）
      const isDanger = p.category === 'red';
      const colorHex = isDanger ? 0xff0033 : 0xffea00;
      const count = 1;

      const pinGroup = new THREE.Group();
      // 底座贴地图表面（街道层 z=0.83）
      pinGroup.position.set(sx, -sy, this.depth + 0.23);
      const PIN_TOP = 0.83;

      // 地面动态发光光圈（Shader 扩散波纹；uOpacity 供淡入动画）
      const rippleSize = (this._pinConfig && this._pinConfig.rippleSize) || 2.0;
      const rippleMat = new THREE.ShaderMaterial({
        transparent: true,
        depthWrite: false,
        depthTest: false,   // 关闭深度测试：波纹贴地面始终可见（不被街道贴图遮挡）
        uniforms: {
          uTime: { value: 0 },
          uColor: { value: new THREE.Color(colorHex) },
          uOpacity: { value: 1 },
        },
        vertexShader: 'varying vec2 vUv; void main(){ vUv=uv; gl_Position = projectionMatrix*modelViewMatrix*vec4(position,1.0); }',
        fragmentShader: [
          'uniform float uTime; uniform vec3 uColor; uniform float uOpacity; varying vec2 vUv;',
          'void main(){',
          '  float dist = distance(vUv, vec2(0.5)); if(dist>0.5) discard;',
          '  float coreGlow = smoothstep(0.18,0.0,dist)*0.85;',
          '  float val = fract(dist*7.0 - uTime*1.5);',
          '  float ring = smoothstep(0.0,0.08,val) - smoothstep(0.08,0.2,val);',
          '  float fade = 1.0 - (dist/0.5);',
          '  float alpha = (ring*0.9 + coreGlow)*fade*uOpacity;',
          '  gl_FragColor = vec4(uColor, alpha);',
          '}',
        ].join('\n'),
      });
      const ripple = new THREE.Mesh(new THREE.PlaneGeometry(rippleSize, rippleSize), rippleMat);
      // 波纹贴地面不动（z=0）；间距由水滴 pinLift 悬浮提供（水滴正上方抬起）
      ripple.position.z = 0;
      ripple.renderOrder = 8;     // 高于街道贴图（7），下钻时波纹不被遮挡
      pinGroup.add(ripple);

      // 倒水滴实体（emissive 自带发光，无虚影壳）
      const pinMat = new THREE.MeshPhongMaterial({
        color: colorHex, emissive: colorHex, emissiveIntensity: 0.6,
        shininess: 100, transparent: true, opacity: 0.95, fog: false,
      });
      const drop = new THREE.Mesh(baseGeo, pinMat);
      // 水滴 renderOrder 高于波纹(8)：波纹 depthTest:false 无深度测试会覆盖一切，
      // 水滴后画(10)且 z 更高 → 深度测试通过 → 水滴盖住波纹，波纹不被其他图钉遮挡
      drop.renderOrder = 10;
      // 图钉组在贴图表面（z=0.83）：波纹贴地面（z=0），水滴悬浮抬起 pinLift（间距=pinLift）
      const lift = (this._pinConfig && this._pinConfig.pinLift) || 0;
      drop.position.z = lift;
      pinGroup.add(drop);

      // 悬浮标签（区县+项目标题 胶囊；hover 才显示）
      const labelDiv = document.createElement('div');
      labelDiv.className = 'pin-label ' + (isDanger ? 'danger' : 'warning');
      labelDiv.title = p.name || '';   // 原生气泡显示完整标题（超长省略号时兜底）
      labelDiv.innerHTML = '<span class="district">' + (p.district || '') + '</span>' +
        '<span class="proj">' + (p.name || '') + '</span>';
      const ls = (this._pinConfig && this._pinConfig.labelScale) || 1;
      if (ls !== 1) labelDiv.style.transform = 'scale(' + ls + ')';
      labelDiv.style.display = 'none';
      labelDiv.style.pointerEvents = 'auto';
      labelDiv.style.cursor = 'pointer';
      labelDiv.onclick = (ev) => {
        if (ev) ev.stopPropagation();
        this._onScatterClick(pinGroup);
      };
      this._pinLabelLayer.appendChild(labelDiv);

      pinGroup.userData = {
        data: p, pin: drop, ripple: ripple, rippleMat: rippleMat, count: count,
        dupKey: key,   // 同坐标组标识（全市折叠/下钻展开）
        nameKey: (p.name || '').trim(),   // 同名组标识（全市态同名折叠，只显示 priority 最高）
        groupKey: groupAssign[pi] || '',   // 近似同名组键（与 2D 同规则：同组只显示一个代表）
        isTop: pi < topCount,   // 全市态只显示 priority 前 maxPins 个
        label: labelDiv, phase: Math.random() * Math.PI * 2,
        origPos: pinGroup.position.clone(),   // 全市态显示位置（可能散开偏移）
        truePos: new THREE.Vector3(tx, -ty, this.depth + 0.23),   // 真实世界坐标（下钻/定位用，不失真）
      };
      group.add(pinGroup);
      this._warningPins.push(pinGroup);
      this._dupGroups.get(key).push(pinGroup);
    });
    // 回填同坐标组成员（一个图钉代表同坐标的多个项目：详情卡片翻页用；标签只显示当前代表）
    const gMap = new Map();
    this._warningPins.forEach(pg => {
      const gk = pg.userData.dupKey || ('g:' + (pg.userData.groupKey || ''));
      if (!gMap.has(gk)) gMap.set(gk, []);
      gMap.get(gk).push(pg);
    });
    this._warningPins.forEach(pg => {
      // 组内成员：同坐标组全部记录（数据库已查重；标签只显示当前代表项目，组内其他靠详情翻页）
      pg.userData.groupMembers = (gMap.get(pg.userData.dupKey || ('g:' + (pg.userData.groupKey || ''))) || [])
        .map(m => m.userData.data);
    });
    group.visible = false;   // 默认隐藏，预警图模式显示
    this.mapGroup.add(group);
    this._warningPinGroup = group;
    // 创建后立即应用已有周期/颜色过滤（页面初始加载时图钉即按当前周期过滤）
    if (this._pinPeriod) this.setPinPeriod(this._pinPeriod);
    if (this._pinFilter) this.setPinFilter(this._pinFilter);
  }

  // 近似同名判定：一方是另一方的前缀且长度差 ≥2 → 同一项目（数据库重复采集，如"基地项目"vs"基地项目车间"）
  _nameSimilar(a, b) {
    if (!a || !b || a === b) return a === b;
    return (a.indexOf(b) === 0 && a.length > b.length + 1) || (b.indexOf(a) === 0 && b.length > a.length + 1);
  }

  // 全市态折叠：近似同名组始终折叠（重复项目防重）；
  // 同坐标组按条数阈值折叠（≤3 条不折叠——不同项目同点散开后各自显示；>3 条折叠——多为重复堆积）。
  // 下钻展开全部由 _repositionPinsForDrill 控制（不受此限制）
  _foldDuplicatePins() {
    if (!this._warningPinGroup) return;
    const MAX_UNFOLD = 3;   // 同坐标组内 ≤3 条不隐藏（导出层已对不同名项目散开坐标，不会重叠）
    const groups = new Map();
    this._warningPins.forEach(pg => {
      const ud = pg.userData;
      const k = ud.dupKey || ('g:' + (ud.groupKey || ''));
      if (!groups.has(k)) groups.set(k, []);
      groups.get(k).push(pg);
    });
    this._warningPins.forEach(pg => {
      const ud = pg.userData;
      const k = ud.dupKey || ('g:' + (ud.groupKey || ''));
      const g = groups.get(k) || [pg];
      const isNameGroup = k.indexOf('g:') === 0;   // 近似同名组 → 始终折叠
      const shouldFold = isNameGroup || g.length > MAX_UNFOLD;
      if (!shouldFold) {
        // 条数在阈值内：不折叠，全部显示（颜色+周期过滤仍生效）
        pg.visible = !!ud.isTop && this._pinFilterMatches(ud) && this._pinPeriodMatches(ud);
        return;
      }
      let rep = g[0];
      g.forEach(m => {
        if ((m.userData.data.priority || 0) > (rep.userData.data.priority || 0)) rep = m;
      });
      // 组代表 + Top 限制内 + 颜色过滤 + 周期过滤（统一叠加：所有调用处自动生效，
      // 包括模式切换 _resetPins、下钻返回全市等，保证 周期×颜色 与数据库一致）
      pg.visible = (pg === rep) && !!ud.isTop &&
        this._pinFilterMatches(ud) && this._pinPeriodMatches(ud);
    });
  }

   // 图钉是否匹配当前过滤（null=全部；对象 {category,type,stage} 组合 AND）
   _pinFilterMatches(ud) {
     if (!this._pinFilter) return true;
     if (!ud || !ud.data) return false;
     const f = this._pinFilter;
     const d = ud.data;
     if (f.category && d.category !== f.category) return false;
     if (f.type && d.project_type !== f.type) return false;
     if (f.stage && d.stage !== f.stage) return false;
     return true;
   }

   // 周期起点（YYYY-MM-DD）：本周=7天前、本月=1号、今年=1月1日；null=不限制
   _periodStartStr() {
     const p = this._pinPeriod;
     if (!p || p === 'all') return '';
     const pad = n => (n < 10 ? '0' + n : String(n));
     const now = new Date();
     if (p === 'week') {
       // 自然周（周一起）：回到本周一
       const d = new Date(now.getFullYear(), now.getMonth(), now.getDate());
       const day = d.getDay();                    // 0=周日
       const diff = (day === 0 ? -6 : 1 - day);
       d.setDate(d.getDate() + diff);
       return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate());
     }
     if (p === 'month') return now.getFullYear() + '-' + pad(now.getMonth() + 1) + '-01';
     if (p === 'year') return now.getFullYear() + '-01-01';
     return '';
   }

   // 图钉是否匹配当前周期（周期 × 颜色 叠加的通用判定，全市态/下钻态共用）
   // 严格过滤：无日期的记录不属于任何周期 → 排除（与统计/柱状图/时间趋势一致，
   // 否则无日期黄色记录会以图钉形式出现 → "本周没有黄色但图钉有黄色" 数据不相符）
   _pinPeriodMatches(ud) {
     const start = this._periodStartStr();
     if (!start) return true;
     const d = String((ud && ud.data && ud.data.publish_date) || '');
     if (!d) return false;
     return d >= start;
   }

   // 周期过滤：图钉按 publish_date 是否在当前周期内显示（本周/本月/今年；null=全部）
   // _foldDuplicatePins 已统一叠加 颜色+周期 过滤，这里仅设置周期并刷新
   setPinPeriod(period) {
     this._pinPeriod = period || null;
     if (!this._warningPinGroup) return;
     if (this._districtMode) {
       // 下钻态：图钉由 _repositionPinsForDrill 控制位置，按当前周期+颜色刷新可见性
       this._warningPins.forEach(pg => {
         pg.visible = pg.visible && this._pinFilterMatches(pg.userData) && this._pinPeriodMatches(pg.userData);
       });
       return;
     }
     this._foldDuplicatePins();   // 内部已叠加 颜色+周期 过滤
     const visCount = this._warningPins.filter(pg => pg.visible).length;
     console.log('[setPinPeriod]', period, '→ 图钉可见', visCount, '/', this._warningPins.length);
   }

   // 预警实时统计联动：切预警图并按颜色过滤图钉（'red'/'yellow'/null=全部）
   setPinFilter(filter) {
     if (filter === 'red' || filter === 'yellow') this._pinFilter = { category: filter };
     else if (filter && typeof filter === 'object') this._pinFilter = filter;
     else this._pinFilter = null;
     if (this._mapMode !== 'warning') this.setMapMode('warning');
     if (!this._warningPinGroup && this._yantaiGeojson) this._addWarningPins();
     // 刷新个体可见性（下钻态由 _repositionPinsForDrill 控制，此处全市态先折叠同坐标再过滤）
     if (!this._districtMode) {
       this._foldDuplicatePins();
       this._warningPins.forEach(pg => {
         pg.visible = pg.visible && this._pinFilterMatches(pg.userData);
       });
     }
     // 重新播放图钉出场动画（只淡入匹配的图钉）
     if (this._pinTimer) clearTimeout(this._pinTimer);
     this._pinTimer = setTimeout(() => {
       if (this._districtMode) this._showPins(); else this._dropInPins();
     }, 400);
   }

   // 图表联动筛选：按 项目类型/阶段 过滤图钉（kind='type'|'stage'，value=类别名，null/缺省=清除该项）
   setChartFilter(kind, value) {
     const cur = this._pinFilter ? Object.assign({}, this._pinFilter) : {};
     if (value) cur[kind] = value;
     else delete cur[kind];
     if (!cur.category && !cur.type && !cur.stage) this._pinFilter = null;
     else this._pinFilter = cur;
     if (!this._warningPinGroup && this._yantaiGeojson) this._addWarningPins();
     if (this._districtMode) {
       // 下钻态：不硬切预警图，保持当前动作；位置已由 _repositionPinsForDrill 定好，只刷新区县内图钉
       const feature = (this._yantaiGeojson.features || [])
         .find(f => f.properties.name === this._currentDrillName);
       this._warningPins.forEach(pg => {
         const ud = pg.userData;
         const v = ud.data && ud.data.value;
         pg.visible = !!(feature && v && v.length >= 2
           && this._isPointInFeature(feature, v[0], v[1])
           && this._pinFilterMatches(ud));
       });
       this._showPins();
     } else {
       // 全市态：切预警图并刷新图钉（先折叠同坐标再过滤）
       if (this._mapMode !== 'warning') this.setMapMode('warning');
       this._foldDuplicatePins();
       this._warningPins.forEach(pg => {
         pg.visible = pg.visible && this._pinFilterMatches(pg.userData);
       });
       if (this._pinTimer) clearTimeout(this._pinTimer);
       this._pinTimer = setTimeout(() => this._dropInPins(), 400);
     }
   }

  // 地图动画就位后图钉直接显示（无淡入动画，纯静态标记；位置由 _repositionPinsForDrill/_resetPins 精确控制）
  _showPins() {
    if (!this._warningPins.length) return;
    this._warningPins.forEach(pg => {
      if (!pg.visible) return;
      const ud = pg.userData;
      if (ud.pin) ud.pin.material.opacity = 0.95;
      if (ud.rippleMat) ud.rippleMat.uniforms.uOpacity.value = 1;
    });
  }

  // 图钉出场动画（GSAP）：透明度淡入（水滴 opacity + 波纹 uOpacity），全部同时（无逐个错开——155+ 图钉逐个等太久）
  // 只动 opacity、不动任何位置 → 不与 _animate 浮动 / 下钻定位 tween 冲突，不引入漂移
  _fadeInPins() {
    if (!this._warningPins.length || typeof gsap === 'undefined') return;
    this._warningPins.forEach((pg) => {
      if (!pg.visible) return;
      const ud = pg.userData;
      const delay = 0.1;
      if (ud.pin) {
        gsap.killTweensOf(ud.pin.material);
        ud.pin.material.opacity = 0;
        gsap.to(ud.pin.material, { opacity: 0.95, duration: 0.6, delay: delay, ease: 'power2.out' });
      }
      if (ud.rippleMat) {
        gsap.killTweensOf(ud.rippleMat.uniforms.uOpacity);
        ud.rippleMat.uniforms.uOpacity.value = 0;
        gsap.to(ud.rippleMat.uniforms.uOpacity, { value: 1, duration: 0.7, delay: delay, ease: 'power2.out' });
      }
    });
  }

  // 仅点击"预警图"按钮时播放：图钉从上往下落入原位 + 透明度淡入（全部同时，无逐个错开）
  _dropInPins() {
    if (!this._warningPins.length || typeof gsap === 'undefined') return;
    this._warningPins.forEach((pg) => {
      if (!pg.visible) return;
      const ud = pg.userData;
      const delay = 0.15;
      if (ud.pin) {
        gsap.killTweensOf(ud.pin.material);
        ud.pin.material.opacity = 0;
        gsap.to(ud.pin.material, { opacity: 0.95, duration: 0.6, delay: delay, ease: 'power2.out' });
      }
      if (ud.rippleMat) {
        gsap.killTweensOf(ud.rippleMat.uniforms.uOpacity);
        ud.rippleMat.uniforms.uOpacity.value = 0;
        gsap.to(ud.rippleMat.uniforms.uOpacity, { value: 1, duration: 0.7, delay: delay, ease: 'power2.out' });
      }
      // 从上往下：先升到上方再落入原位（整组：水滴+波纹）；只动 z 不动 x/y → 与下钻定位 tween 不冲突
      const z0 = pg.position.z;
      gsap.killTweensOf(pg.position);
      pg.position.z = z0 + 0.9;
      gsap.to(pg.position, { z: z0, duration: 0.7, delay: delay, ease: 'power3.out' });
    });
  }

  // 下钻时：区县内的图钉随区县放大位置（GSAP 动画与区县缩放同步，点位精确），区县外隐藏
  _repositionPinsForDrill(center, sxy) {
    this._pinSolo = null;   // 下钻重建 → 退出独显模式
    if (!this._warningPinGroup) return;
    const feature = (this._yantaiGeojson.features || [])
      .find(f => f.properties.name === this._currentDrillName);
    const dur = (this._flyMs || 1500) / 1000;
    // 同坐标组微抖动（与 2D 重叠视觉基本一致，微错开可区分点击）：
    // r=0.05 世界单位 ≈ 0.6km，下钻视野内轻微分开可点，不会推出陆地
    const fanOffset = (idx) => {
      const golden = 2.399963;
      const r = 0.05;
      return { x: Math.cos(idx * golden) * r, y: Math.sin(idx * golden) * r };
    };
    const dupIdx = new Map();   // dupKey → 已分配序号（不再展开，保留微抖备用）
    // 下钻折叠（与全市态/2D 一致：同坐标组合并成一个图钉，标签显示组内全部项目）：
    // 阶段1：同坐标组（dupKey）选 priority 最高代表
    // 阶段2：近似同名跨坐标去重（如"三期"在 A/B 两坐标都有记录 → 只保留 priority 最高的一个位置）
    const rep1 = new Map();
    this._warningPins.forEach(pg => {
      const ud = pg.userData;
      const v = ud.data && ud.data.value;
      if (!(feature && v && v.length >= 2 && this._isPointInFeature(feature, v[0], v[1]))) return;
      if (!this._pinFilterMatches(ud)) return;
      if (!this._pinPeriodMatches(ud)) return;   // 下钻同样叠加周期过滤（与全市态一致）
      const k = ud.dupKey || ('c:' + (ud.groupKey || ''));
      const cur = rep1.get(k);
      if (!cur || ((ud.data.priority || 0) > (cur.userData.data.priority || 0))) rep1.set(k, pg);
    });
    const rep2 = new Map();
    rep1.forEach(pg => {
      const k = 'g:' + (pg.userData.groupKey || '');
      const cur = rep2.get(k);
      if (!cur || ((pg.userData.data.priority || 0) > (cur.userData.data.priority || 0))) rep2.set(k, pg);
    });
    const finalReps = new Set(rep2.values());
    this._warningPins.forEach(pg => {
      const ud = pg.userData;
      const v = ud.data && ud.data.value;
      if (feature && v && v.length >= 2 && this._isPointInFeature(feature, v[0], v[1])) {
        // 同坐标组合并 + 近似同名跨坐标去重后：只有最终代表显示；再叠加红黄/类型/阶段过滤
        pg.visible = finalReps.has(pg) && this._pinFilterMatches(ud);
        const o = ud.truePos || ud.origPos;   // 下钻用真实坐标（散开只影响全市态显示）
        // 围绕区县中心按放大倍率缩放位置（mapGroup 局部：x=地理x，y=-geoY，z=高度）
        // center 是挤出体世界包围盒中心：worldZ = -localY = geoY（南为正）
        // → 本地 y 缩放：localY' = -center.z + (o.y + center.z)*sxy
        const tx = center.x + (o.x - center.x) * sxy;
        const ty = -center.z + (o.y + center.z) * sxy;
        let fx = 0, fy = 0;
        if (ud.dupKey) {
          const n = dupIdx.get(ud.dupKey) || 0;
          dupIdx.set(ud.dupKey, n + 1);
          const off = fanOffset(n);
          fx = off.x; fy = off.y;
        }
        if (typeof gsap !== 'undefined') {
          gsap.killTweensOf(pg.position);
          gsap.to(pg.position, { x: tx + fx, y: ty + fy, z: 0.83, duration: dur, ease: 'power3.out' });
        } else {
          pg.position.set(tx + fx, ty + fy, 0.83);
        }
      } else {
        // 区县外图钉：下钻时隐藏（只留区县内图钉，干净聚焦）；返回全市时由 _resetPins 恢复
        pg.visible = false;
      }
    });
  }

  // 返回全市：图钉位置直接还原到原始坐标（无动画，避免回位 tween 被淡入 tween 覆盖导致漂移）+ 单个可见性按模式恢复
  _resetPins() {
    this._pinSolo = null;   // 全量重建可见性 → 退出独显模式
    if (!this._warningPinGroup) return;
    const show = this._mapMode === 'warning';
    this._warningPins.forEach(pg => {
      const o = pg.userData.origPos;
      if (typeof gsap !== 'undefined') gsap.killTweensOf(pg.position);   // 清掉下钻缩放残留 tween，防止位置漂移
      pg.position.copy(o);
    });
    // 全市态：同坐标只显示一个（priority 最高），再叠加过滤
    if (show) {
      this._foldDuplicatePins();
      this._warningPins.forEach(pg => {
        pg.visible = pg.visible && this._pinFilterMatches(pg.userData);
      });
    } else {
      this._warningPins.forEach(pg => { pg.visible = false; });
    }
  }

  // 点 (lng,lat) 是否在区县多边形内（射线法）
  _isPointInFeature(feature, lng, lat) {
    const t = feature.geometry.type;
    const polys = t === 'MultiPolygon' ? feature.geometry.coordinates : [feature.geometry.coordinates];
    for (let k = 0; k < polys.length; k++) {
      let inside = false;
      for (const ring of polys[k]) {
        for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
          const xi = ring[i][0], yi = ring[i][1];
          const xj = ring[j][0], yj = ring[j][1];
          if ((yi > lat) !== (yj > lat) && lng < (xj - xi) * (lat - yi) / (yj - yi) + xi) {
            inside = !inside;
          }
        }
      }
      if (inside) return true;
    }
    return false;
  }

  // ==================== 动画循环 ====================
  _animate() {
    if (this.isDestroyed) return;
    this._rafId = requestAnimationFrame(this._animate);

    const delta = this.clock.getDelta();
    const elapsedTime = this.clock.getElapsedTime();

    // 侧面纹理流动 (对齐 ThreeMaps 速度 0.005)
    if (this.sideMaterial && this.sideMaterial.map) {
      this.sideMaterial.map.offset.y += 0.005;
    }

    // 轮廓描边纹理流动 (对齐 ThreeMaps 速度 0.005)
    if (this.strokeMaterial && this.strokeMaterial.map) {
      this.strokeMaterial.map.offset.x += 0.005;
    }

    // 扩散波纹
    if (this.diffuseShader && this.diffuseShader.pointShader) {
      this._diffuseTime += delta;
      const maxTime = 60 / 8.0;
      const uTime = this._diffuseTime % maxTime;
      this.diffuseShader.pointShader.uniforms.uTime.value = uTime;
    }

    // 飞线 & 粒子 tick
    this._tickCallbacks.forEach(cb => cb(delta, elapsedTime));

    // 旋转圆环
    if (this.rotatePlane1) this.rotatePlane1.update();
    if (this.rotatePlane2) this.rotatePlane2.update();

    // 散点 Sprite 呼吸动画
    this.scatterItems.forEach(group => {
      const sprite = group.userData.sprite;
      if (sprite) {
        const t = Math.sin(elapsedTime * 2.5) * 0.2 + 0.8;  // 0.6 ~ 1.0 呼吸范围
        const s = (group.userData.baseScale || 0.14) * t;
        sprite.scale.set(s, s, 1);
      }
    });

    // 预警图 3D 图钉：地面波纹 + 上下漂浮 + 悬浮胶囊标签（屏幕投影）
    if (this._warningPins && this._warningPins.length) {
      const _wv = this._pinWv || (this._pinWv = new THREE.Vector3());
      const w = this.width || 1920, h = this.height || 1080;
      this._warningPins.forEach(pinGroup => {
        const ud = pinGroup.userData;
        if (!ud || !ud.rippleMat || !pinGroup.parent) return;
        ud.rippleMat.uniforms.uTime.value = elapsedTime;
        if (ud.pin) {
          // 上下浮动：叠加在悬浮高度 pinLift 上（只动水滴 z，不影响 x/y → 不会导致位置漂移）
          const amp = (this._pinConfig && this._pinConfig.floatAmp) || 0.08;
          const lift = (this._pinConfig && this._pinConfig.pinLift) || 0;
          ud.pin.position.z = lift + Math.sin(elapsedTime * 2.4 + ud.phase) * amp;
        }
        // 波纹贴地面不动（z=0，位置由创建时固定）
        if (ud.label) {
          // 标签仅 hover 或选中的图钉显示（避免杂乱）
          if (!pinGroup.visible || (pinGroup !== this._hoverPin && pinGroup !== this._selectedPin)) {
            ud.label.style.display = 'none';
          } else {
            pinGroup.getWorldPosition(_wv);
            // 标签贴悬浮水滴顶部（水滴抬起 pinLift，标签相对水滴再上移 0.6，不过高）
            _wv.y += ((this._pinConfig && this._pinConfig.pinLift) || 0) + 0.6;
            _wv.project(this.camera);
            if (_wv.z > 0 && _wv.z < 1) {
              ud.label.style.display = 'flex';   // 必须 flex：覆盖 CSS 默认，否则内容块级顶格
              ud.label.style.transform =
                'translate(' + ((_wv.x + 1) / 2 * w) + 'px,' + ((-_wv.y + 1) / 2 * h) + 'px) translate(-50%, -100%)';
            } else {
              ud.label.style.display = 'none';
            }
          }
        }
      });
    }

    // 相机飞行期间跳过 controls.update（否则每帧按 target 距离重算位置，GSAP 会被覆盖），
    // 但必须手动 lookAt 飞行目标，否则相机朝向不更新
    if (!this._switching) {
      this.controls.update();
      // 下钻模式：拖拽范围限制（target 距区县中心超过半径则拉回，避免拖进空白海域）
      if (this._districtMode && this._panCenter && this._panRadius) {
        const d = this.controls.target.clone().sub(this._panCenter);
        if (d.lengthSq() > this._panRadius * this._panRadius) {
          d.setLength(this._panRadius);
          this.controls.target.copy(this._panCenter).add(d);
          this.controls.update();
        }
      }
    } else if (this.controls) {
      this.camera.lookAt(this.controls.target);
    }
    this.renderer.render(this.scene, this.camera);

    // CSS3D
    if (this.label3d) this.label3d.update();
  }

  // ==================== 区县交互：悬浮高亮 / 点击下钻 / 再点返回 ====================
  _initInteraction() {
    this._raycaster = new THREE.Raycaster();
    // 悬浮高亮材质（对齐广东：亮色 clone）
    if (this._faceMat) {
      this._hoverFaceMat = this._faceMat.clone();
      this._hoverFaceMat.color.set(0x73d0ff);
      this._hoverFaceMat.opacity = 0.85;
    }
    if (this._strokeMat) {
      this._hoverStrokeMat = this._strokeMat.clone();
      this._hoverStrokeMat.color.set(0x9be8ff);
    }
    // 模糊轮廓材质（下钻时其他区县底衬）
    // 颜色/透明度要明显区别于深蓝背景（0x102736 + ocean），否则看不见
    this._blurFaceMat = new THREE.MeshBasicMaterial({
      color: 0x1d4f78, transparent: true, opacity: 0.7, fog: false,
    });
    this._blurTopMat = new THREE.MeshLambertMaterial({
      color: 0x12304a, transparent: true, opacity: 0.45, fog: false,
    });
    this._blurSideMat = new THREE.MeshLambertMaterial({
      color: 0x0a1d30, transparent: true, opacity: 0.35, fog: false,
    });
    // 底衬轮廓：暗色不发光细线（用户要求去掉发光边缘）
    this._blurStrokeMat = new THREE.MeshBasicMaterial({
      color: 0x2e5f8a, transparent: true, opacity: 0.8, fog: false,
    });
    this._hoveredName = null;
    this._districtMode = false;
    this._switching = false;
    this._pinFilter = null;       // 预警图图钉颜色过滤：'red' / 'yellow' / null=全部
    this._noStreetData = false;   // 街道数据文件缺失标志（避免每次下钻 404）
    this._mapMode = 'bar';        // 显示模式：bar=柱状图 / heat=热力图 / warning=预警图
    this._flyMs = 1500;           // 动画时长（毫秒，与 drillFlyTime 同步）
    this._downX = undefined;
    this._downY = undefined;
    this._clickReady = false;
    // 高德瓦片窗口状态
    this._windowAuto = false;      // 街道窗口自动刷新开关
    this._tileFallbackUsed = false;
    this._cityStaticShown = false; // 城市总览是否已用静态 yantai.jpg
    this._windowTimer = null;
    this._returnState = null;      // 进入 2D 时捕获的 3D 状态（返回用）
    this._winToken = 0;
    this._lastWindowKey = '';
    this._streetCtx = null;        // 下钻区县贴图上下文（bbox+polys）
    this._lastDrillZ = -1;
    this._infoCard = null;
    this._cityPolysCache = null;
    // 相机变化 → 街道窗口防抖刷新（高德手感：放大自动换更清晰瓦片；200ms 让缩放跟手）
    this._windowChangeB = () => {
      if (!this._windowAuto || this._switching) return;
      if (this._windowTimer) clearTimeout(this._windowTimer);
      this._windowTimer = setTimeout(() => this._refreshStreetWindow(), 200);
    };
    this.controls.addEventListener('change', this._windowChangeB);
    // 与 2D 高德地图协调：进入 2D 捕获状态，返回恢复（定位回选中区县）
    if (window.GaodeMap2D) {
      window.GaodeMap2D.onEnter = () => this._captureFor2D();
      window.GaodeMap2D.onExit = () => this._restoreFrom2D();
    }
    // 底部模式按钮（index.html .bottom-menu-item：柱状图/预警图）
    const modeNames = ['bar', 'warning'];
    document.querySelectorAll('.bottom-menu-item').forEach((btn, i) => {
      if (!modeNames[i]) return;
      btn.addEventListener('click', () => {
        // 点"预警图"按钮 = 展示全部图钉（清除统计卡联动过滤，即使已在预警图模式）
        if (modeNames[i] === 'warning') this.setPinFilter(null);
        else this.setMapMode(modeNames[i]);
      });
    });
    if (this._entranceTl) {
      // 入场动画播完即释放（kill timeline），不常驻占用资源；
      // 切换动画已改为相机飞行方案（_switchDistrict/_flyBackCity），不缩放地图
      this._entranceTl.eventCallback('onComplete', () => {
        this._clickReady = true;
        // 记录入场动画结束后的真实相机位置（受 maxPolarAngle clamp 后的稳定位置），
        // 返回时飞回它，避免被 clamp 造成卡顿
        if (this.camera) this._cityCamPos = this.camera.position.clone();
        try {
          this._entranceTl.kill();
        } catch (e) {}
        this._entranceTl = null;
      });
    } else {
      this._clickReady = true;
    }
    // 统一的"全市地图"按钮（fixed 顶层，避免点击区县返回与图钉卡片互相误触；
    // 3D 下钻时显示；2D 打开时也显示——点击先退出 2D 再返回全市，与 2D 的返回按钮统一为一个）
    if (!document.getElementById('drill-back')) {
      this._drillBackBtn = document.createElement('div');
      this._drillBackBtn.id = 'drill-back';
      this._drillBackBtn.className = 'drill-back';
      this._drillBackBtn.textContent = '全市地图';
      this._drillBackBtn.style.display = 'block';   // 常驻显示（用户要求一直在导航栏）
      this._drillBackBtn.onclick = () => {
        // 2D 打开时先退出（onExit 恢复 3D 相机到下钻区县），再返回全市
        if (window.GaodeMap2D && window.GaodeMap2D.isVisible && window.GaodeMap2D.isVisible()) {
          window.GaodeMap2D.hide();
        }
        this._switchCity();
      };
      // 放入顶部右侧导航（"今年"胶囊按钮左侧，随导航 flex 排列）
      const navRight = document.querySelector('.head-nav.nav-right');
      const yearGroup = navRight && navRight.querySelector('.head-mq-date');
      if (yearGroup) {
        navRight.insertBefore(this._drillBackBtn, yearGroup);
      } else {
        document.body.appendChild(this._drillBackBtn);
      }
    }
    const dom = this.renderer.domElement;
    this._onPointerMoveB = this._onPointerMove.bind(this);
    this._onPointerDownB = this._onPointerDown.bind(this);
    this._onClickB = this._onClick.bind(this);
    dom.addEventListener('pointermove', this._onPointerMoveB);
    dom.addEventListener('pointerdown', this._onPointerDownB);
    dom.addEventListener('click', this._onClickB);
  }

  // "全市地图"按钮：常驻顶部导航（今年胶囊左侧，与左侧"本周/本月"对称），
  // 不再随下钻/2D 显隐；点击返回全市（2D 打开时先退出 2D）
  _updateDrillBackBtn() {
    if (!this._drillBackBtn) return;
    this._drillBackBtn.style.display = 'block';
  }

  // 切换地图显示模式：bar=柱状图（柱+标签）/ heat=热力图 / warning=预警图（干净地图）
  setMapMode(mode) {
    if (this._mapMode === mode) return;
    this._mapMode = mode;
    // 按钮 active 样式（热力图按钮已移除）
    const names = ['bar', 'warning'];
    document.querySelectorAll('.bottom-menu-item').forEach((b, i) => {
      b.classList.toggle('is-active', names[i] === mode);
    });
    // 柱状图模式：柱+标签 + 入场动画；热力图：高德瓦片街道底图；预警图：3D 图钉干净地图
    const isWarning = mode === 'warning';
    // 预警图模式显示 3D 图钉（隐藏 Sprite 散点 + 莱山飞线/聚焦光圈）；其他模式反之
    if (isWarning && !this._warningPinGroup && this._yantaiGeojson) this._addWarningPins();
    if (this._warningPinGroup) {
      // 可见性：预警图 = 显示；柱状图下钻态 = 联动显示该区县图钉；其余隐藏
      const pinVisible = isWarning || (mode === 'bar' && this._districtMode);
      this._warningPinGroup.visible = pinVisible;
      if (pinVisible && this._districtMode && this._drillCenter) {
        // 已下钻时切到预警图/柱状图：图钉按下钻中心重新定位
        this._repositionPinsForDrill(this._drillCenter, this._currentScaleXY || 1);
      } else if (isWarning && !this._districtMode) {
        // 全市态切预警图：恢复全部图钉个体可见性 + 位置归位
        // （bar 模式返回全市时 _resetPins 按模式把个体 visible 置 false，需在这里还原）
        this._resetPins();
        // 折叠同坐标组（只显示 priority 最高的代表），避免重复图钉
        this._foldDuplicatePins();
      }
    }
    // 莱山飞线/聚焦光圈：预警图（干净地图）隐藏
    if (this.flyLine) this.flyLine.instance.visible = !isWarning;
    if (this.focus) this.focus.visible = !isWarning;
    // 坐标类文字标签：区县名标签预警图隐藏；"烟台市"城市标签保留显示
    if (this._districtLabelGroup) this._districtLabelGroup.visible = !isWarning;
    if (this._focusLabel) this._focusLabel.show();
    if (this._districtNameLabel) { if (isWarning) this._districtNameLabel.hide(); }
    this.scatterItems.forEach(g => { g.visible = !isWarning; });
    // 仅点击"预警图"按钮时图钉从上往下淡入；已下钻则直接显示（不与下钻定位 tween 打架）
    if (isWarning && !this._switching) {
      if (this._pinTimer) clearTimeout(this._pinTimer);
      this._pinTimer = setTimeout(() => {
        if (this._districtMode) this._showPins(); else this._dropInPins();
      }, 400);
    }
    if (mode === 'bar') {
      if (this.barGroup) this.barGroup.visible = true;
      if (this.barLabelGroup) this.barLabelGroup.visible = true;
      this.allBarLabels.forEach(l => { if (l && l.show) l.show(); });
      // 模式切换数据一致性：切回柱状图仍按导航栏周期（本周/本月/今年）呈现
      // 用导航栏当前周期（window.getMqPeriod），而非 _pinPeriod（页面初始未点按钮时为 null → 全量数据 bug）
      if (typeof window !== 'undefined' && window.buildDistrictRanking) {
        try {
          var mqPeriod = (window.getMqPeriod ? window.getMqPeriod() : null) || this._pinPeriod || 'week';
          this.updateBars(window.buildDistrictRanking(mqPeriod));
        } catch (e) {}
      }
      this._removeHeatLayer();
      this._stopWindowAutoRefresh();
      this._playCityReturnAnimation();   // 柱子长高 + 标签滑入入场
    } else if (mode === 'heat') {
      if (this.barGroup) this.barGroup.visible = false;
      this.allBarLabels.forEach(l => { if (l && l.hide) l.hide(); });
      // 热力图图层已移除：heat 模式不再加载街道底图（按钮已删，此分支为防御）
      this._removeHeatLayer();
      this._stopWindowAutoRefresh();
} else {  // warning
      // 从下钻态切到预警图：自动返回全市（_flyBackCity onComplete 恢复全部图钉，
      // 避免 _repositionPinsForDrill 只留当前区县图钉）
      if (this._districtMode && !this._switching) this._switchCity();
      if (this.barGroup) this.barGroup.visible = false;
      this.allBarLabels.forEach(l => { if (l && l.hide) l.hide(); });
      // 模式切换数据一致性：切到预警图时图钉按当前周期+颜色刷新（_resetPins+fold 已叠加）
      if (this._pinPeriod) this.setPinPeriod(this._pinPeriod);
      this._removeHeatLayer();
      this._stopWindowAutoRefresh();
    }
  }

  // 热力图模式：加载烟台全市街道底图贴图（js/district-tiles/yantai.jpg）
  _loadCityTile() {
    this._removeHeatLayer();
    const geojson = this._yantaiGeojson;
    const polys = [];
    (geojson.features || []).forEach(f => {
      const t = f.geometry.type;
      const ps = t === 'MultiPolygon' ? f.geometry.coordinates : [f.geometry.coordinates];
      ps.forEach(p => polys.push(p));
    });
    let minLng = Infinity, maxLng = -Infinity, minLat = Infinity, maxLat = -Infinity;
    polys.forEach(poly => poly.forEach(ring => ring.forEach(p => {
      minLng = Math.min(minLng, p[0]); maxLng = Math.max(maxLng, p[0]);
      minLat = Math.min(minLat, p[1]); maxLat = Math.max(maxLat, p[1]);
    })));
    if (!(maxLng > minLng && maxLat > minLat)) return;
    const img = new Image();
    img.onload = () => {
      if (this.isDestroyed || this._mapMode !== 'heat') return;
      this._finishStreetLayer(img, polys, minLng, maxLng, minLat, maxLat, true);
    };
    img.onerror = () => {
      console.log('[底图] 无文件 js/district-tiles/yantai.jpg，跳过');
    };
    img.src = 'js/district-tiles/yantai.jpg';
  }

  // 移除热力图全市底图
  _removeHeatLayer() {
    if (this._heatLayer) {
      this.focusMapGroup.remove(this._heatLayer);
      if (this._heatLayer.geometry) this._heatLayer.geometry.dispose();
      if (this._heatLayer.material) {
        if (this._heatLayer.material.map) this._heatLayer.material.map.dispose();
        if (this._heatLayer.material.alphaMap) this._heatLayer.material.alphaMap.dispose();
        this._heatLayer.material.dispose();
      }
      this._heatLayer = null;
    }
  }

  // 命中区县名（只检测顶面 mesh）
  _getHit(e) {
    const rect = this.renderer.domElement.getBoundingClientRect();
    const mouse = new THREE.Vector2(
      ((e.clientX - rect.left) / rect.width) * 2 - 1,
      -((e.clientY - rect.top) / rect.height) * 2 + 1
    );
    this._raycaster.setFromCamera(mouse, this.camera);
    // 预警点散点（Sprite）优先于地图
    // 注：预警图 3D 图钉点击不走射线——用屏幕距离判定（_pinAtScreen，更稳）
    if (this.scatterItems.length) {
      const sprites = [];
      this.scatterItems.forEach(g => { if (g.userData && g.userData.sprite) sprites.push(g.userData.sprite); });
      const sh = this._raycaster.intersectObjects(sprites, false);
      if (sh.length > 0) {
        const group = this.scatterItems.find(g => g.userData && g.userData.sprite === sh[0].object);
        if (group) return { name: null, scatter: group };
      }
    }
    const hits = this._raycaster.intersectObjects(
      this.intersectMeshes.filter(m => m.userData.isMapFace || m.userData.isDistrict), false
    );
    if (hits.length > 0 && hits[0].object.userData.name) {
      return { name: hits[0].object.userData.name, scatter: null };
    }
    return null;
  }

  _onPointerMove(e) {
    const hit = this._getHit(e);
    // 下钻模式：所有区县都不 hover（当前区/底衬均不高亮）
    const name = (hit && !hit.scatter) ? hit.name : null;
    this._setHover(name);
    // 预警图图钉 hover：鼠标距图钉屏幕位置 <60px → 上浮标签
    if (this._warningPinGroup && this._warningPinGroup.visible) {
      let nearest = null, best = 60 * 60;
      const rect = this.renderer.domElement.getBoundingClientRect();
      const mx = e.clientX - rect.left, my = e.clientY - rect.top;
      const _wv = this._pinWv || (this._pinWv = new THREE.Vector3());
      const lift = (this._pinConfig && this._pinConfig.pinLift) || 0;
      this._warningPins.forEach(pg => {
        if (!pg.visible) return;
        pg.getWorldPosition(_wv);
        _wv.y += lift;            // hover 判定对准悬浮抬起后的水滴（波纹贴地面不动）
        _wv.project(this.camera);
        const px = (_wv.x + 1) / 2 * rect.width, py = (-_wv.y + 1) / 2 * rect.height;
        const d = (mx - px) * (mx - px) + (my - py) * (my - py);
        if (d < best) { best = d; nearest = pg; }
      });
      // 标签停留：鼠标离开图钉后延迟 250ms 再隐藏，用户可移过去点击标签（否则移开即消失点不到）
      if (this._hoverTimer) clearTimeout(this._hoverTimer);
      if (nearest) {
        this._hoverPin = nearest;
      } else {
        this._hoverTimer = setTimeout(() => { this._hoverPin = null; }, 250);
      }
      // 有选中图钉时（日志/图钉点击选中）不响应 hover，避免标签互相覆盖
      if (this._selectedPin) this._hoverPin = null;
    }
    if (this.renderer.domElement) {
      const overPin = hit && hit.scatter;
      this.renderer.domElement.style.cursor = (overPin || name) ? 'pointer' : 'default';
    }
  }

  _onPointerDown(e) {
    this._downX = e.clientX;
    this._downY = e.clientY;
  }

  _onClick(e) {
    // 拖拽旋转/缩放后松开不算点击
    if (this._downX !== undefined &&
      (Math.abs(e.clientX - this._downX) > 5 || Math.abs(e.clientY - this._downY) > 5)) return;
    if (!this._clickReady || this._switching) return;
    // 预警图：点击图钉（屏幕距离 24px 内）→ 弹卡片；点区县其他地方正常下钻
    if (this._warningPinGroup && this._warningPinGroup.visible) {
      const pg = this._pinAtScreen(e.clientX, e.clientY, 24);
      if (pg) {
        this._hideScatterCard(true);   // 点击其他预警点：旧卡片先消失（keepMode：独显切换不恢复模式）
        this._onScatterClick(pg);
        return;
      }
    }
    const hit = this._getHit(e);
    if (hit && hit.scatter) {
      // 预警点散点 → 信息卡片
      this._hideScatterCard(true);   // 点击其他预警点：旧卡片先消失（keepMode：独显切换不恢复模式）
      this._onScatterClick(hit.scatter);
      return;
    }
    // 点击地图空白（未点中图钉/散点）：关闭已打开的详情卡片
    if (this._infoCard && this._infoCard.style.display === 'block') {
      this._hideScatterCard();
      return;
    }
    const name = hit ? hit.name : null;
    // 下钻模式点击不再返回（返回走"返回全市"按钮，避免点区县误触与图钉卡片混淆）
    if (!this._districtMode) {
      if (name) this._switchDistrict(name);   // 大地图行为不变
    }
  }

  // 悬浮高亮：顶面 + 描边替换为亮色 clone，离开恢复
  _setHover(name) {
    if (this._hoveredName === name) return;
    if (this._hoveredName) this._applyHighlight(this._hoveredName, false);
    this._hoveredName = name;
    if (name) {
      this._applyHighlight(name, true);
      if (this.renderer.domElement) this.renderer.domElement.style.cursor = 'pointer';
    } else if (this.renderer.domElement) {
      this.renderer.domElement.style.cursor = 'default';
    }
  }

  _applyHighlight(name, on) {
    // 顶面基准：下钻模式下非当前区 = 模糊材质，当前区/全市 = 正常
    const baseFace = (this._districtMode && name !== this._currentDrillName)
      ? this._blurFaceMat : this._faceMat;
    // 顶面 BaseMap（group.userData.name 匹配）
    if (this.baseMap) {
      this.baseMap.mapGroup.children.forEach(group => {
        if (group.userData && group.userData.name === name) {
          group.traverse((child) => {
            if (child.isMesh) child.material = on ? this._hoverFaceMat : baseFace;
          });
        }
      });
    }
    // 流光描边 Line（children 顺序与 coordinates 一致，底衬保留发光描边）
    if (this.borderLine && this.coordinates) {
      const idx = this.coordinates.findIndex(c => c.name === name);
      const lg = this.borderLine.lineGroup.children[idx];
      if (lg) {
        lg.traverse((child) => {
          if (child.isMesh) child.material = on ? this._hoverStrokeMat : this._strokeMat;
        });
      }
    }
  }

  // ==================== 点击下钻：地图不动，相机飞到区县上方 ====================
  _switchDistrict(name) {
    if (this._districtMode || this._switching) return;
    const feature = (this._yantaiGeojson.features || []).find(f => f.properties.name === name);
    if (!feature) return;
    this._setHover(null);
    this._hideScatterCard();   // 切换区县：详情卡片先消失

    // ===== 下钻视距参数（可调，改完 F5 生效） =====
    // 占屏比例 0.75 = 大地图垂直屏占比 74.6%（分析实测），调小=区县更小
    var drillPadding = 0.75;
    // 俯视角弧度 ≈46°（飞过去后视角高，无需手动再调），调小=更低0.8
    var drillTilt = 0.8;
    // 相机飞行时长（秒，与返回生长动画同步）—— 动画速度调整处
    var drillFlyTime = 1.5;
    this._flyMs = Math.round(drillFlyTime * 1000);   // 同步到生长/上升动画时长
    // =============================================

    // ===== 烟台市全区县配置（视距由数学公式全自动计算，此处仅保留 shift 偏移量与 tilt 角度微调） =====
    var districtTune = {
      '芝罘区': { shift: [-1, -0.3],scaleXY: 8,size: 0.7 },
      '福山区': { shift: [0, 0],scaleXY: 4,size: 0.8 },
      '莱山区': { shift: [0, 0],scaleXY: 7,size: 0.7,labelNorth: 2.0},
      '牟平区': { shift: [0, 0],scaleXY: 4,size: 0.6 },
      '蓬莱区': { shift: [0, 6.5],scaleXY: 3,size: 0.45},
      '龙口市': { shift: [0, 0],scaleXY: 4,size: 0.55 },
      '莱州市': { shift: [0, 0],scaleXY: 4,size: 0.5 },
      '招远市': { shift: [0, 0],scaleXY: 4,size: 0.55 },
      '栖霞市': { shift: [0, 0],scaleXY: 4,size: 0.5 },
      '海阳市': { shift: [0, -2.1],scaleXY: 2.6,size: 0.6 },
      '莱阳市': { shift: [0, 0],scaleXY: 4,size: 0.55 }
    };
    var tune = districtTune[name] || { shift: [0, 0] };
    var tilt = tune.tilt || drillTilt;   // 每区可覆盖全局俯角
    this._currentTune = tune;            // 供 _applyBlurMode（旋转）使用
    // ================================================================

    // 1) 世界包围盒（ExtrudeMap feature group，children 顺序与 coordinates 一致）
    const idx = this.coordinates.findIndex(c => c.name === name);
    if (idx < 0 || !this.extrudeMap || !this.extrudeMap.mapGroup.children[idx]) return;
    const box = new THREE.Box3().setFromObject(this.extrudeMap.mapGroup.children[idx]);
    const size = box.getSize(new THREE.Vector3());
    const center = box.getCenter(new THREE.Vector3());
    this._drillCenter = center;   // 供预警图图钉下钻缩放使用

    // 2) 区县大小分级 → 平铺放大倍率（小区县放更大，突出顶面）
    const maxDim = Math.max(size.x, size.z);
    let scaleXY = 1.2;
    if (maxDim < 5.0) { scaleXY = 5.5; }        // 小区县 2.2
    else if (maxDim < 8.0) { scaleXY = 2.6; }   // 中区县 1.6
    if (tune.scaleXY) scaleXY = tune.scaleXY;   // 每区可覆盖自动放大倍率（districtTune 里配）
    this._currentScaleXY = scaleXY;

    // 3) 视距全自动自适应计算（视距按放大后的尺寸算，放大后占屏一致、不出屏）
    const fovRad = (this.camera.fov * Math.PI) / 180;
    const aspect = this.width / this.height;

    // 考虑相机倾斜视角(tilt)后，模型在屏幕投影中的实际占用宽高（×放大倍率）
    const effectiveHeight = (size.z * Math.sin(tilt) + size.y * Math.cos(tilt)) * scaleXY;
    const effectiveWidth = size.x * scaleXY;

    // 计算让区县刚好填满屏幕宽高所需的视距
    const distForWidth = (effectiveWidth / (2 * Math.tan(fovRad / 2) * aspect));
    const distForHeight = (effectiveHeight / (2 * Math.tan(fovRad / 2)));

    // 取最大视距并乘 1.9（视野放大：区县占屏约 35%，能看到整个区县全貌+周边环境；
    // 要再缩小/放大调这个系数，调大=区县更小视野更大）
    const baseDist = Math.max(distForWidth, distForHeight) * 1.9;
    const dist = baseDist * (tune.size || 1.0);

    // 3) 相机飞行目标（世界坐标；shift 正 = 右/屏幕下方）
    const targetPos = new THREE.Vector3(
      center.x + tune.shift[0], 0.2, center.z + tune.shift[1]
    );
    const camPos = new THREE.Vector3(
      center.x + tune.shift[0],
      0.2 + dist * Math.sin(tilt),
      center.z + tune.shift[1] + dist * Math.cos(tilt)
    );

    // 3.5) 下钻拖拽范围限制（找位置用）：中心=区县，半径≈可见视口半宽的一半（约屏幕1/4）
    this._panCenter = targetPos.clone();
    this._panRadius = dist * Math.tan(fovRad / 2) * aspect * 0.5;

    // 4) 其他区县 → 模糊轮廓底衬；当前区保持正常
    this._currentDrillName = name;
    this._districtMode = true;
    if (window.onDistrictDrill) window.onDistrictDrill(name);   // 下钻 → 左栏类型/阶段图表按区县过滤
    this._updateDrillBackBtn();   // 显示"返回全市"按钮
    this._applyBlurMode(name);
    this._removeHeatLayer();   // 下钻时移除热力图全市底图（避免遮挡区县）
    console.log('[下钻] 4-blur:', name, 'idx:', idx, '挤出体visible:', this.extrudeMap.mapGroup.children[idx] ? this.extrudeMap.mapGroup.children[idx].visible : '无');

    // 5) 街道底图（统一投影直接绘制，与地图绝对对齐）
    this._loadStreetTiles(feature);

    // 6) 隐藏全市点缀元素（地图本身不动）
    if (this.flyLine) this.flyLine.instance.visible = false;
    if (this.focus) this.focus.visible = false;
    if (this.barGroup) this.barGroup.visible = false;
    if (this.barLabelGroup) this.barLabelGroup.visible = false;
    // CSS3DRenderer 不检查 Group.visible，必须用 label.hide()（visibility:hidden）才真正隐藏
    this.allBarLabels.forEach(l => { if (l && l.hide) l.hide(); });
    if (this._districtLabelGroup) this._districtLabelGroup.visible = false;
    if (this._focusLabel) this._focusLabel.hide();
    this.scatterItems.forEach(g => { g.visible = false; });
    // 预警图模式：区县内图钉随下钻放大保持在相应位置；柱状图模式：下钻联动显示该区县预警图钉；其他模式隐藏
    if (this._mapMode === 'bar' && !this._warningPinGroup && this._yantaiGeojson) this._addWarningPins();
    if (this._warningPinGroup) {
      if (this._mapMode === 'warning' || this._mapMode === 'bar') {
        this._warningPinGroup.visible = true;
        this._repositionPinsForDrill(center, scaleXY);
      } else {
        this._warningPinGroup.visible = false;
      }
    }

    // 6.5) 区名大标签（"莱山区 DISTRICT"，复用焦点标签样式）
    if (this.label3d) {
      if (!this._districtNameLabel) {
        this._districtNameLabel = this.label3d.create('', 'map-focus-label', false);
        this.label3d.setLabelStyle(this._districtNameLabel, 0.015, 'x');
        this._districtNameLabel.setParent(this.mapGroup);
      }
      // 与全市模式"烟台市"标签同位置语义：区县中心经度 + 北边上方 + 北移300px
      // 方向：世界 z 增大 = 屏幕下方；往屏幕上方（北）移 = 世界 z 减小
      const labelNorth = tune.labelNorth || 0;   // 每区可额外北移（districtTune 里配，正=更靠北）
      const labelZ = targetPos.z - size.z * 0.22 - 9.6 - labelNorth;
      this._districtNameLabel.init(
        `<div class="focus-label-wrap"><span class="focus-label-zh">${name}</span><span class="focus-label-en">DISTRICT</span></div>`,
        new THREE.Vector3(targetPos.x, -labelZ, 0.4)
      );
      this._districtNameLabel.show();
    }

    // 7) GSAP 相机飞行（飞行期间锁定 OrbitControls）
    this._switching = true;
    this.controls.enabled = false;
    console.log('[下钻] 7-飞行:', 'target', targetPos.x.toFixed(2), targetPos.z.toFixed(2), 'cam', camPos.x.toFixed(2), camPos.y.toFixed(2), camPos.z.toFixed(2));
    gsap.killTweensOf(this.camera.position);
    gsap.killTweensOf(this.controls.target);
    gsap.to(this.controls.target, {
      x: targetPos.x, y: targetPos.y, z: targetPos.z,
      duration: drillFlyTime, ease: 'power3.inOut',
    });
    gsap.to(this.camera.position, {
      x: camPos.x, y: camPos.y, z: camPos.z,
      duration: drillFlyTime, ease: 'power3.inOut',
      onComplete: () => {
        this._switching = false;
        this.controls.enabled = true;
        // 预警图：地图就位后图钉直接显示（静态标记，位置已在 _repositionPinsForDrill 精确就位）
        if (this._mapMode === 'warning') this._showPins();
      },
    });
  }

  // ==================== 再点一下：相机飞回烟台全市 ====================
  _switchCity() {
    if (!this._districtMode || this._switching) return;
    this._setHover(null);

    // 移除街道底图贴图层
    this._disposePlane(this._streetLayer);
    this._streetLayer = null;
    this._streetCtx = null;
    this._lastDrillZ = -1;
    this._stopWindowAutoRefresh();

    // ① 先压扁其他区县（与恢复同帧）；底衬平面保持在底部，描边先去掉
    if (this.extrudeMap && this.coordinates) {
      this.coordinates.forEach((c, i) => {
        const g = this.extrudeMap.mapGroup.children[i];
        if (!g || c.name === this._currentDrillName) return;
        g.visible = true;
        g.scale.set(1, 1, 0.01);   // 压扁（高度 z）
        if (this.baseMap && this.baseMap.mapGroup.children[i]) {
          this.baseMap.mapGroup.children[i].position.z = -1.0;  // 底衬平面保持底部
        }
        if (this.borderLine && this.borderLine.lineGroup.children[i]) {
          this.borderLine.lineGroup.children[i].visible = false;  // 描边先去掉
        }
      });
    }

    // ② 恢复所有区县正常材质（位置由上升动画接管）
    this._restoreCityMode();
    this._districtMode = false;
    if (window.onDistrictDrill) window.onDistrictDrill(null);   // 返回全市 → 图表恢复全量
    this._updateDrillBackBtn();   // 隐藏"返回全市"按钮
    // 当前区的描边直接恢复（其他区等底衬平面上升完成后再加）
    if (this.borderLine && this.coordinates) {
      const idx = this.coordinates.findIndex(c => c.name === this._currentDrillName);
      const lg = this.borderLine.lineGroup.children[idx];
      if (lg) lg.visible = true;
    }

    // 恢复显示（柱状图模式才恢复柱子和标签；热力图/预警图保持干净地图）
    const isWarning = this._mapMode === 'warning';
    if (this.flyLine) this.flyLine.instance.visible = !isWarning;
    if (this.focus) this.focus.visible = !isWarning;
    if (this._mapMode === 'bar') {
      if (this.barGroup) this.barGroup.visible = true;
      if (this.barLabelGroup) this.barLabelGroup.visible = true;
      this.allBarLabels.forEach(l => { if (l && l.show) l.show(); });
      // 返回全市：柱状图强制按当前周期刷新（导航栏筛选为第一优先级——
      // 修复"本周下钻后返回，柱状图不是本周数据"）
      if (this._pinPeriod && typeof window !== 'undefined' && window.buildDistrictRanking) {
        try { this.updateBars(window.buildDistrictRanking(this._pinPeriod)); } catch (e) {}
      }
    }
    if (this._districtLabelGroup) this._districtLabelGroup.visible = !isWarning;
    if (this._focusLabel) this._focusLabel.show();   // "烟台市"城市标签始终显示
    if (this._districtNameLabel) this._districtNameLabel.hide();
    this.scatterItems.forEach(g => { g.visible = this._mapMode !== 'warning'; });
    if (this._warningPinGroup) {
      // 返回动画期间隐藏图钉，区县恢复原位后由 _flyBackCity onComplete 显示+淡入
      this._warningPinGroup.visible = false;
    }
    // 相机飞回 + 其他区县：挤出体生长 + 底衬平面慢慢上升回表面（同步 1.5s），描边最后加上
    this._flyBackCity();
    if (this.extrudeMap && this.coordinates) {
      this.coordinates.forEach((c, i) => {
        const g = this.extrudeMap.mapGroup.children[i];
        if (!g || c.name === this._currentDrillName) return;
        this._growDistrict(g, this._flyMs);
        if (this.baseMap && this.baseMap.mapGroup.children[i]) {
          this._animateZ(this.baseMap.mapGroup.children[i], 0, this._flyMs, () => {
            // 底衬平面回到表面后，再加上描边（不再悬浮）
            if (this.borderLine && this.borderLine.lineGroup.children[i]) {
              this.borderLine.lineGroup.children[i].visible = true;
            }
          });
        }
      });
    }
    this._playCityReturnAnimation();
  }

  // 区县从扁平（高度 0.01）平滑长成立体
  // 独立 requestAnimationFrame 自循环（不依赖 gsap/_tickCallbacks，绝对可靠），easeInOutCubic
  _growDistrict(g, duration) {
    if (!g) return;
    g.visible = true;
    g.scale.set(1, 1, 0.01);
    const start = performance.now();
    const dur = duration || 1500;
    const step = () => {
      if (this.isDestroyed) return;
      const t = Math.min(1, (performance.now() - start) / dur);
      const e = t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;  // easeInOutCubic
      g.scale.z = 0.01 + 0.99 * e;
      if (t < 1) {
        requestAnimationFrame(step);
      } else {
        g.scale.set(1, 1, 1);
      }
    };
    requestAnimationFrame(step);
  }

  // 对象 position.z 从当前值平滑动画到目标值（独立 RAF，easeInOutCubic）
  _animateZ(obj, to, duration, onDone) {
    if (!obj) { if (onDone) onDone(); return; }
    const from = obj.position.z;
    const start = performance.now();
    const dur = duration || 1500;
    const step = () => {
      if (this.isDestroyed) return;
      const t = Math.min(1, (performance.now() - start) / dur);
      const e = t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;  // easeInOutCubic
      obj.position.z = from + (to - from) * e;
      if (t < 1) {
        requestAnimationFrame(step);
      } else if (onDone) {
        onDone();
      }
    };
    requestAnimationFrame(step);
  }

  // 相机飞回全市（入场动画结束后的真实位置，避免 maxPolarAngle clamp 卡顿）
  _flyBackCity() {
    if (typeof gsap === 'undefined') return;
    const dest = this._cityCamPos || { x: -0.17, y: 9.68, z: 20.69 };
    this._switching = true;
    this.controls.enabled = false;
    gsap.killTweensOf(this.camera.position);
    gsap.killTweensOf(this.controls.target);
    gsap.to(this.controls.target, { x: 0, y: 0, z: 0, duration: 1.5, ease: 'power3.inOut' });
    gsap.to(this.camera.position, {
      x: dest.x, y: dest.y, z: dest.z,
      duration: 1.5, ease: 'power3.inOut',
      onComplete: () => {
        this._switching = false;
        this.controls.enabled = true;
        // 区县恢复原位后图钉位置无条件归位（可见性按模式：预警图显示全部，柱状图隐藏）
        if (this._warningPinGroup) {
          this._resetPins();
          if (this._mapMode === 'warning') {
            this._warningPinGroup.visible = true;
            this._fadeInPins();
          }
        }
      },
    });
  }

  // ==================== 模糊轮廓底衬（对齐广东 China 轮廓：地图下方平面的一层 + 发光轮廓线） ====================
  // 下钻时：其他区县 → 顶面暗色平面并下移到地图下方 + 挤出体隐藏 + 描边换亮色发光轮廓
  _applyBlurMode(name) {
    // 当前区旋转（districtTune.rot，绕垂直轴；mapGroup 旋转后局部 z = 世界 y）
    const tune = this._currentTune || {};
    const rotRad = (tune.rot || 0) * Math.PI / 180;
    this._currentRot = rotRad;

    // 顶面 BaseMap：非当前区 → 暗色平面 + 下移；当前区直接隐藏（避免"两个区县"重影）
    if (this.baseMap) {
      this.baseMap.mapGroup.children.forEach(group => {
        if (!group.userData || !group.userData.name) return;
        const isCurrent = group.userData.name === name;
        group.visible = !isCurrent;         // 当前区顶面隐藏
        group.position.z = isCurrent ? 0 : -1.0;   // 底衬下移到地图下方
        group.rotation.z = 0;
        if (!isCurrent) {
          group.traverse((child) => {
            if (child.isMesh) child.material = this._blurFaceMat;
          });
        }
      });
    }
    // 挤出体 ExtrudeMap：非当前区隐藏（平面底衬，只有当前区保持立体）+ 当前区旋转+平铺放大
    if (this.extrudeMap && this.coordinates) {
      this.coordinates.forEach((c, i) => {
        const g = this.extrudeMap.mapGroup.children[i];
        if (!g) return;
        g.visible = c.name === name;
        if (c.name === name) {
          g.rotation.z = rotRad;
          this._scaleDistrictKeepCenter(g, this._currentScaleXY || 1.0);
          // 挤出体 mesh 加入拾取（带 name，供点击放大后的区县返回）
          g.traverse((child) => {
            if (child.isMesh) {
              child.userData.name = name;
              child.userData.isDistrict = true;
              if (!this.intersectMeshes.includes(child)) this.intersectMeshes.push(child);
            }
          });
        }
      });
    }
    // 描边 Line：下钻时全部隐藏（当前区立体也不加描边，底衬只要平面）
    if (this.borderLine && this.coordinates) {
      this.coordinates.forEach((c, i) => {
        const lg = this.borderLine.lineGroup.children[i];
        if (!lg) return;
        lg.visible = false;
      });
    }
  }

  // 绕区县几何中心"平铺放大 + 侧壁压薄"，保持中心不动（ExtrudeMap group 原点在投影原点，需补偿）
  _scaleDistrictKeepCenter(g, sxy) {
    if (typeof gsap === 'undefined' || !g) return;
    const parent = g.parent;
    // 缩放前中心（父局部空间）
    const pre = new THREE.Box3().setFromObject(g).getCenter(new THREE.Vector3());
    parent.worldToLocal(pre);
    // 预计算缩放后的中心（position 暂为 0），求补偿量
    g.scale.set(sxy, sxy, 0.3);
    g.updateMatrixWorld(true);
    const post = new THREE.Box3().setFromObject(g).getCenter(new THREE.Vector3());
    parent.worldToLocal(post);
    const delta = pre.clone().sub(post);   // 补偿量（父局部）
    g.scale.set(1, 1, 1);
    g.position.set(0, 0, 0);
    // GSAP 动画：放大 + 压薄 + 中心补偿（与相机飞行同步）
    const dur = (this._flyMs || 1500) / 1000;
    gsap.killTweensOf(g.scale);
    gsap.killTweensOf(g.position);
    gsap.to(g.scale, { x: sxy, y: sxy, z: 0.3, duration: dur, ease: 'power3.out' });
    gsap.to(g.position, { x: delta.x, y: delta.y, z: delta.z, duration: dur, ease: 'power3.out' });
  }

  // 恢复所有区县正常 3D 材质（位置由上升动画接管；描边 visible 由 _switchCity 控制；旋转复位）
  _restoreCityMode() {
    if (this.baseMap) {
      this.baseMap.mapGroup.children.forEach(group => {
        group.visible = true;   // 恢复顶面显示（下钻时当前区被隐藏）
        group.rotation.z = 0;   // 旋转复位
        group.position.z = 0;   // 底衬回地图表面（上升动画接管前先归位）
        group.traverse((child) => {
          if (child.isMesh) child.material = this._faceMat;
        });
      });
    }
    if (this.extrudeMap) {
      this.extrudeMap.mapGroup.traverse((child) => {
        if (child.isMesh) child.material = [this._topMat, this.sideMaterial];
      });
      this.extrudeMap.mapGroup.children.forEach(g => {
        if (g) {
          g.visible = true;
          g.rotation.z = 0;
          // GSAP 缩回动画（scale → 1，position 补偿 → 0），避免闪现
          if (typeof gsap !== 'undefined' && (g.scale.x !== 1 || g.scale.z !== 1)) {
            gsap.killTweensOf(g.scale);
            gsap.killTweensOf(g.position);
            gsap.to(g.scale, { x: 1, y: 1, z: 1, duration: (this._flyMs || 1500) / 1000, ease: 'power3.inOut' });
            gsap.to(g.position, { x: 0, y: 0, z: 0, duration: (this._flyMs || 1500) / 1000, ease: 'power3.inOut' });
          } else {
            g.scale.set(1, 1, 1);
            g.position.set(0, 0, 0);
          }
        }
      });
    }
    if (this.borderLine) {
      this.borderLine.lineGroup.traverse((child) => {
        if (child.isMesh) child.material = this._strokeMat;
      });
    }
    this._currentRot = 0;
  }

  // 返回大地图动画：柱子从 0 长高 + 柱标签依次滑入淡入（地图本身不动）
  _playCityReturnAnimation() {
    if (typeof gsap === 'undefined') return;
    // 柱子生长（高度方向 z 从 0 → 1）
    this.allBars.forEach((box, i) => {
      gsap.killTweensOf(box.scale);
      box.scale.set(1, 1, 0);
      gsap.to(box.scale, { z: 1, duration: 0.5, ease: 'power3.out', delay: 0.25 + i * 0.08 });
    });
    // 柱标签：从右下滑入 + 淡入（对齐开场动画）
    this.allBarLabels.forEach((label, i) => {
      const wrap = label.element.querySelector('.bar-label-wrap');
      if (wrap) {
        gsap.killTweensOf(wrap);
        gsap.fromTo(wrap,
          { x: '40%', y: '40%', opacity: 0 },
          { x: '0%', y: '0%', opacity: 1, duration: 0.6, ease: 'circ.out', delay: 0.35 + i * 0.1 });
      }
    });
  }

  // 地图从扁平（高度 0）生长为立体（复用开场 GSAP 生长机制）
  // 下钻飞行时不调用；返回全市时调用，让地图"长起来"而不是闪现
  _playSwitchAnimation() {
    if (!this.focusMapGroup || typeof gsap === 'undefined') return;
    gsap.killTweensOf(this.focusMapGroup.scale);
    this.focusMapGroup.scale.set(0.85, 0.85, 0.01);
    gsap.to(this.focusMapGroup.scale, {
      x: 1, y: 1, z: 1,
      duration: 0.9,
      ease: 'power3.out',
    });
  }
  // ==================== 区县街道底图贴图（高德瓦片实时；静态 jpg 兜底） ====================
  _loadStreetTiles(feature) {
    this._disposePlane(this._streetLayer);
    this._streetLayer = null;
    const name = feature.properties.name;
    const t = feature.geometry.type;
    const polys = t === 'MultiPolygon' ? feature.geometry.coordinates : [feature.geometry.coordinates];
    let minLng = Infinity, maxLng = -Infinity, minLat = Infinity, maxLat = -Infinity;
    polys.forEach(poly => poly.forEach(ring => ring.forEach(p => {
      minLng = Math.min(minLng, p[0]); maxLng = Math.max(maxLng, p[0]);
      minLat = Math.min(minLat, p[1]); maxLat = Math.max(maxLat, p[1]);
    })));
    if (!(maxLng > minLng && maxLat > minLat)) return;

    this._streetCtx = { polys, minLng, maxLng, minLat, maxLat };
    this._lastDrillZ = -1;
    this._windowAuto = true;   // 下钻后相机缩放时瓦片自动换级
    // 下钻请求最高 z，由瓦片数上限自动选最清晰级别（区县放大后不失真）
    const z = 17;
    this._fetchTileCanvas(this._streetCtx, z).then(res => {
      if (!this._districtMode || this.isDestroyed) return;
      if (res) {
        this._lastDrillZ = z;
        // 平面覆盖区县 bbox（中心对齐），画布按其实际瓦片范围精确定位（imgRange）
        this._finishStreetLayer(res.canvas, polys, minLng, maxLng, minLat, maxLat, false, {
          west: res.bbox.minLng, east: res.bbox.maxLng, south: res.bbox.minLat, north: res.bbox.maxLat,
        });
      } else {
        this._loadStaticStreetTile(name, polys, minLng, maxLng, minLat, maxLat);
      }
    });
  }

  // 静态区县贴图兜底（js/district-tiles/{区名}.jpg）
  _loadStaticStreetTile(name, polys, minLng, maxLng, minLat, maxLat) {
    const img = new Image();
    img.onload = () => {
      if (!this._districtMode || this.isDestroyed) return;
      this._finishStreetLayer(img, polys, minLng, maxLng, minLat, maxLat);
    };
    img.onerror = () => {
      console.log('[底图] 无文件 js/district-tiles/' + name + '.jpg，跳过');
    };
    img.src = 'js/district-tiles/' + encodeURIComponent(name) + '.jpg';
  }

  // 生成街道底图贴图层：Plane 覆盖区县 bbox（当前投影）+ 区县形状遮罩 + 跟随旋转
  // isCity=true 时存 _heatLayer（热力图全市底图），否则存 _streetLayer（下钻区县底图）
  // imgRange（可选）：img 画布实际覆盖的地理范围；提供时画布按 pxs 精确定位（不拉伸铺满），
  //   保证瓦片画布与平面/遮罩严格对齐（消除瓦片网格取整导致的错位）
  _finishStreetLayer(img, polys, minLng, maxLng, minLat, maxLat, isCity, imgRange) {
    // 当前投影下的区县范围
    // 注意：地图 mesh（BaseMap/ExtrudeMap/Line）统一用 -y（北=上方、y 增大），
    // 这里取反对齐，避免 h 塌缩成 1e-6 导致贴图不可见、且上下颠倒
    const [xMin, yNorth] = this.geoProject([minLng, maxLat]);   // 北 原始 y
    const [xMax, ySouth] = this.geoProject([maxLng, minLat]);   // 南 原始 y
    const w = Math.max(Math.abs(xMax - xMin), 1e-6);
    const yTop = -yNorth, yBot = -ySouth;                        // 取反后北在上
    const h = Math.max(yTop - yBot, 1e-6);
    const cx = (xMin + xMax) / 2, cy = (yTop + yBot) / 2;

    // 遮罩：区县形状（投影映射 → canvas）
    // 分辨率按源图原生尺寸（上限 2048），不再压到 512 → 清晰度修复
    const srcW = (img.naturalWidth || img.width) || 2048;
    const W = Math.max(256, Math.min(srcW, 2048));
    const H = Math.max(64, Math.min(2048, Math.round(W * h / w)));
    const maskCanvas = document.createElement('canvas');
    maskCanvas.width = W;
    maskCanvas.height = H;
    const mctx = maskCanvas.getContext('2d');
    mctx.fillStyle = '#ffffff';
    const pxs = (lng, lat) => {
      const [x, y] = this.geoProject([lng, lat]);
      return [(x - xMin) / w * W, (yTop + y) / h * H];
    };
    polys.forEach(poly => poly.forEach(ring => {
      if (ring.length < 3) return;
      mctx.beginPath();
      const [sx, sy] = pxs(ring[0][0], ring[0][1]);
      mctx.moveTo(sx, sy);
      for (let i = 1; i < ring.length; i++) {
        const [ex, ey] = pxs(ring[i][0], ring[i][1]);
        mctx.lineTo(ex, ey);
      }
      mctx.closePath();
      mctx.fill('evenodd');
    }));

    // 底图重采样到遮罩同尺寸 → 纹理
    const texCanvas = document.createElement('canvas');
    texCanvas.width = W;
    texCanvas.height = H;
    const cctx = texCanvas.getContext('2d');
    if (imgRange) {
      // 画布按其地理范围定位到平面（与遮罩同一 pxs 映射）→ 严格对齐，不拉伸错位
      const [dx, dy] = pxs(imgRange.west, imgRange.north);
      const [ex, ey] = pxs(imgRange.east, imgRange.south);
      cctx.drawImage(img, dx, dy, ex - dx, ey - dy);
    } else {
      cctx.drawImage(img, 0, 0, W, H);
    }
    // 区县界限描边（叠加到纹理上，让高德街道图上各区县边界清晰可见）
    cctx.strokeStyle = 'rgba(0, 222, 255, 0.9)';
    cctx.lineWidth = Math.max(2, W / 420);
    cctx.lineJoin = 'round';
    polys.forEach(poly => poly.forEach(ring => {
      if (ring.length < 3) return;
      cctx.beginPath();
      const [sx, sy] = pxs(ring[0][0], ring[0][1]);
      cctx.moveTo(sx, sy);
      for (let i = 1; i < ring.length; i++) {
        const [ex, ey] = pxs(ring[i][0], ring[i][1]);
        cctx.lineTo(ex, ey);
      }
      cctx.closePath();
      cctx.stroke();
    }));

    const tex = new THREE.CanvasTexture(texCanvas);
    tex.colorSpace = THREE.SRGBColorSpace;
    // 各向异性过滤：近距/斜视角贴图更锐利
    tex.anisotropy = this.renderer && this.renderer.capabilities
      ? this.renderer.capabilities.getMaxAnisotropy() : 4;
    const maskTex = new THREE.CanvasTexture(maskCanvas);
    maskTex.anisotropy = tex.anisotropy;

    const mat = new THREE.MeshBasicMaterial({
      map: tex,
      alphaMap: maskTex,
      transparent: true,
      opacity: 1,
      fog: false,
      depthWrite: false,
    });
    const geo = new THREE.PlaneGeometry(w, h);
    const mesh = new THREE.Mesh(geo, mat);
    mesh.position.set(cx, cy, this.depth + 0.23);
    mesh.renderOrder = 7;
    mesh.rotation.z = this._currentRot || 0;   // 跟随区县旋转
    // 街道底图绕 bbox 中心（position 即中心）缩放 → 与平铺放大的区县保持对齐
    if (!isCity && this._currentScaleXY) {
      if (this._switching && typeof gsap !== 'undefined') {
        // 下钻展开中：贴图平面与区县 GSAP 同步放大（紧贴 3D 板，不闪现）
        const dur = (this._flyMs || 1500) / 1000;
        gsap.killTweensOf(mesh.scale);
        gsap.to(mesh.scale, { x: this._currentScaleXY, y: this._currentScaleXY, z: 1, duration: dur, ease: 'power3.out' });
      } else {
        mesh.scale.set(this._currentScaleXY, this._currentScaleXY, 1);
      }
    }
    // 淡入过渡：贴图轻柔出现（下钻展开/缩放换级不"闪现"）
    if (typeof gsap !== 'undefined') {
      mat.opacity = 0;
      gsap.killTweensOf(mat);
      gsap.to(mat, { opacity: 1, duration: 0.35, ease: 'power2.out' });
    }
    this.focusMapGroup.add(mesh);
    if (isCity) {
      this._heatLayer = mesh;
    } else {
      this._streetLayer = mesh;
    }
  }


  // ==================== 高德瓦片街道窗口（动态贴图，跟随相机，无需 key） ====================
  // 热力图模式 / 预警点街道聚焦：按相机视野拉取高德瓦片拼贴到地图表面，放大自动换更清晰
  _disposePlane(plane) {
    if (!plane) return;
    this.focusMapGroup.remove(plane);
    if (plane.geometry) plane.geometry.dispose();
    if (plane.material) {
      if (plane.material.map) plane.material.map.dispose();
      if (plane.material.alphaMap) plane.material.alphaMap.dispose();
      plane.material.dispose();
    }
  }

  // 相机距离 → 高德缩放级别（3D 场景内合理上限 z15；超出由瓦片数上限兜底降级）
  _zoomFromDistance(dist) {
    if (dist > 26) return 10;
    if (dist > 18) return 11;
    if (dist > 12) return 12;
    if (dist > 8) return 13;
    if (dist > 5) return 14;
    return 15;
  }

  // 相机可见地理范围（地图平铺在世界 XZ 平面 y≈0.2）：目标点距离 + fov 估算，留余量
  _visibleGeoBBox() {
    return this._bboxForView(this.controls.target.x, this.controls.target.z, null);
  }

  // 指定世界视点 (wx, wz) + 相机距离 → 可见地理范围（供街道聚焦预取）
  _bboxForView(wx, wz, dist) {
    const d = dist || this.camera.position.distanceTo(new THREE.Vector3(wx, 0, wz)) || 1;
    const fov = this.camera.fov * Math.PI / 180;
    const vh = 2 * d * Math.tan(fov / 2);
    const vw = vh * this.camera.aspect;
    // 世界(X,Z) → 地理（rawY = -worldZ），投影中心附近线性近似
    const [clng, clat] = this.projection.invert([wx, -wz]);
    const [ex1, ey1] = this.projection([clng + 1, clat]);
    const [ex0, ey0] = this.projection([clng, clat]);
    const [nx1, ny1] = this.projection([clng, clat + 1]);
    // 该投影不取反 Y：纬度越大 y 越小 → 单位跨度取绝对值，保证 minLat<maxLat
    const degPerUnitX = 1 / Math.abs((ex1 - ex0) || 1e-9);
    const degPerUnitY = 1 / Math.abs((ny1 - ey0) || 1e-9);
    const margin = 1.25;
    return {
      minLng: clng - vw * degPerUnitX * margin / 2,
      maxLng: clng + vw * degPerUnitX * margin / 2,
      minLat: clat - vh * degPerUnitY * margin / 2,
      maxLat: clat + vh * degPerUnitY * margin / 2,
      dist: d,
    };
  }

  // 全市多边形容器（窗口遮罩用，缓存）
  _getCityPolys() {
    if (this._cityPolysCache) return this._cityPolysCache;
    const geojson = this._yantaiGeojson;
    const polys = [];
    (geojson.features || []).forEach(f => {
      const t = f.geometry.type;
      const ps = t === 'MultiPolygon' ? f.geometry.coordinates : [f.geometry.coordinates];
      ps.forEach(p => polys.push(p));
    });
    this._cityPolysCache = polys;
    return polys;
  }

  // 全市地理包围盒（城市总览瓦片裁剪用，缓存）
  _getCityBBox() {
    if (this._cityBBox) return this._cityBBox;
    const polys = this._getCityPolys();
    let minLng = Infinity, maxLng = -Infinity, minLat = Infinity, maxLat = -Infinity;
    polys.forEach(poly => poly.forEach(ring => ring.forEach(p => {
      minLng = Math.min(minLng, p[0]); maxLng = Math.max(maxLng, p[0]);
      minLat = Math.min(minLat, p[1]); maxLat = Math.max(maxLat, p[1]);
    })));
    this._cityBBox = { minLng, maxLng, minLat, maxLat };
    return this._cityBBox;
  }

  // 拉取瓦片拼贴画布；失败返回 null（调用方回退静态 jpg）
  // 返回 { canvas, bbox }：bbox = 实际瓦片网格覆盖的地理范围（画布与平面精确对齐的关键）
  _fetchTileCanvas(bbox, z, maxTiles) {
    if (!window.GaodeTiles) return Promise.resolve(null);
    return window.GaodeTiles.fetchStitched(
      bbox.minLng, bbox.maxLng, bbox.minLat, bbox.maxLat, z,
      { maxTiles: maxTiles || 256 }
    ).then(r => {
      if (!r) return null;
      const rb = window.GaodeTiles.rangeBounds(r.range, r.z);
      return {
        canvas: r.canvas,
        bbox: { minLng: rb.west, maxLng: rb.east, minLat: rb.south, maxLat: rb.north },
      };
    }).catch(() => null);
  }

  // 激活城市/热力图瓦片窗口（预警点街道聚焦也走这里）
  _activateStreetWindow() {
    if (!this._yantaiGeojson || !window.GaodeTiles) return;
    this._getCityBBox();   // 预热城市范围缓存（窗口裁剪用）
    this._cityStaticShown = false;
    this._windowAuto = true;
    if (this._windowTimer) { clearTimeout(this._windowTimer); this._windowTimer = null; }
    this._refreshStreetWindow();
  }

  _stopWindowAutoRefresh() {
    this._windowAuto = false;
    if (this._windowTimer) { clearTimeout(this._windowTimer); this._windowTimer = null; }
  }

  // 刷新城市窗口（相机跟随：可见范围 + 距离选 z）
  _refreshStreetWindow() {
    if (!this._windowAuto || this.isDestroyed || this._switching) return;
    if (this._districtMode) { this._refreshStreetLayerDrill(); return; }
    const bbox = this._visibleGeoBBox();
    // 城市总览（未贴近，dist>12）：用静态 yantai.jpg（1 次请求、即时高清），不拉几百张瓦片
    if (bbox.dist > 12) {
      if (!this._cityStaticShown) {
        this._cityStaticShown = true;
        this._loadCityTile();
      }
      return;
    }
    // 贴近后：实时高德瓦片（窗口裁剪到全市范围）
    this._cityStaticShown = false;
    if (this._cityBBox) {
      bbox.minLng = Math.max(bbox.minLng, this._cityBBox.minLng);
      bbox.maxLng = Math.min(bbox.maxLng, this._cityBBox.maxLng);
      bbox.minLat = Math.max(bbox.minLat, this._cityBBox.minLat);
      bbox.maxLat = Math.min(bbox.maxLat, this._cityBBox.maxLat);
    }
    const z = this._zoomFromDistance(bbox.dist);
    const key = z + '/' + Math.floor(bbox.minLng * 1e5) + '/' + Math.floor(bbox.maxLng * 1e5) +
      '/' + Math.floor(bbox.minLat * 1e5) + '/' + Math.floor(bbox.maxLat * 1e5);
    if (key === this._lastWindowKey) return;
    this._lastWindowKey = key;
    const token = ++this._winToken;
    this._fetchTileCanvas(bbox, z).then(res => {
      if (token !== this._winToken || !this._windowAuto || this.isDestroyed) return;
      if (!res) {
        // 离线兜底：静态 yantai.jpg（仅一次）
        if (!this._tileFallbackUsed) {
          this._tileFallbackUsed = true;
          this._loadCityTile();
        }
        return;
      }
      this._tileFallbackUsed = false;
      this._disposePlane(this._heatLayer);
      this._heatLayer = null;
      // 用实际瓦片网格范围建平面，画布与平面同范围 → 无拉伸错位
      this._finishStreetLayer(res.canvas, this._getCityPolys(),
        res.bbox.minLng, res.bbox.maxLng, res.bbox.minLat, res.bbox.maxLat, true);
    });
  }

  // 下钻区县：固定区县 bbox，瓦片保持最高可用 z（清晰度不随相机距离降低）
  _refreshStreetLayerDrill() {
    const ctx = this._streetCtx;
    if (!ctx) return;
    const z = 17;
    if (z === this._lastDrillZ) return;
    this._lastDrillZ = z;
    const token = ++this._winToken;
    this._fetchTileCanvas(ctx, z).then(res => {
      if (!res || token !== this._winToken || !this._windowAuto || this.isDestroyed) return;
      this._disposePlane(this._streetLayer);
      this._streetLayer = null;
      // 平面覆盖区县 bbox，画布按实际瓦片范围精确定位（imgRange）
      this._finishStreetLayer(res.canvas, ctx.polys,
        ctx.minLng, ctx.maxLng, ctx.minLat, ctx.maxLat, false, {
          west: res.bbox.minLng, east: res.bbox.maxLng, south: res.bbox.minLat, north: res.bbox.maxLat,
        });
    });
  }

  // 预警点散点点击：信息卡片
  // 屏幕距离判定：点击位置附近（<threshold px）的可见图钉（比 3D 射线稳定）
  _pinAtScreen(cx, cy, threshold) {
    if (!this._warningPinGroup || !this._warningPinGroup.visible) return null;
    // 强制刷新世界矩阵：图钉位置被 GSAP 动画驱动，避免旧矩阵导致拦截判定偏移
    if (this.scene) this.scene.updateMatrixWorld();
    const rect = this.renderer.domElement.getBoundingClientRect();
    const _wv = this._pinWv || (this._pinWv = new THREE.Vector3());
    const th = threshold || 40;
    let best = null, bestD = th * th;
    const lift = (this._pinConfig && this._pinConfig.pinLift) || 0;
    this._warningPins.forEach(pg => {
      if (!pg.visible) return;
      pg.getWorldPosition(_wv);
      _wv.y += lift;            // 点击判定对准悬浮抬起后的水滴（波纹贴地面不动）
      _wv.project(this.camera);
      const px = (_wv.x + 1) / 2 * rect.width + rect.left;
      const py = (-_wv.y + 1) / 2 * rect.height + rect.top;
      const d = (cx - px) * (cx - px) + (cy - py) * (cy - py);
      if (d < bestD) { bestD = d; best = pg; }
    });
    return best;
  }

  _onScatterClick(g) {
    this._selectedPin = g;   // 图钉点击/日志点击 → 选中常显标签
    // 独显模式中点击其他图钉 → 切换独显目标
    if (this._pinSolo && g) {
      this._pinSolo = g;
      this._warningPins.forEach(pg => { pg.visible = (pg === g); });
    }
    const data = g.userData && g.userData.data;
    if (!data || !data.value || data.value.length < 2) return;
    // 卡片定位在图标右侧（屏幕坐标；对准悬浮抬起后的水滴）
    const v = g.position.clone();
    g.getWorldPosition(v);
    v.y += (this._pinConfig && this._pinConfig.pinLift) || 0;
    v.project(this.camera);
    let sx, sy;
    // 图钉在当前视野内（NDC z∈[0,1]）才贴图钉定位；视野外（日志点击的场景）用默认右上角，卡片不出屏
    if (v.z > 0 && v.z < 1) {
      sx = (v.x + 1) / 2 * (this.width || 1920);
      sy = (-v.y + 1) / 2 * (this.height || 1080);
    }
    // 组内翻页：同坐标组合并的图钉，卡片可翻看组内所有项目
    const members = (g.userData && g.userData.groupMembers) || [data];
    const idx = members.indexOf(data);
    this._showScatterCard(data, sx, sy, members, idx < 0 ? 0 : idx);
  }

  // 项目详情匹配：数据自身（MySQL 全字段，导出自 export_dashboard_db.py）优先 → workbuddy → project_list 兜底
  _matchProjectDetail(data) {
    // 数据自带数据库全字段（location/ai_reason/developer 等）→ 直接用数据本身
    if (data && data.location !== undefined && data.ai_reason !== undefined) {
      return { src: 'db', row: data };
    }
    const nm = (data.name || '').trim();
    const matcher = (name) => {
      const full = (name || '').trim();
      if (!full || !nm) return false;
      return full === nm || (nm.length > 4 && full.indexOf(nm) === 0) || (full.length > 4 && nm.indexOf(full) === 0);
    };
    const wb = window.DASHBOARD_WORKBUDDY || [];
    for (let i = 0; i < wb.length; i++) {
      const it = wb[i] || {};
      if (it.district === data.district && matcher(it.project_name)) return { src: 'workbuddy', row: it };
    }
    const pl = (window.DASHBOARD_DATA && window.DASHBOARD_DATA.project_list) || [];
    for (let i = 0; i < pl.length; i++) {
      const it = pl[i] || {};
      if (it.district === data.district && matcher(it.name)) return { src: 'project_list', row: it };
    }
    return { src: 'none', row: null };
  }

  _showScatterCard(data, sx, sy, members, idx) {
    const [lng, lat] = data.value;
    const memList = (members && members.length > 1) ? members : null;
    const curIdx = (memList && idx !== undefined) ? idx : 0;
    const cls = data.category === 'red' ? 'red' : 'yellow';
    // 打开详情：hover 标签隐藏（_animate 不再显示非 hover 标签）
    this._hoverPin = null;
    const esc = (s) => String(s === undefined || s === null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    const row = (label, val) => (val !== undefined && val !== null && String(val).trim() !== '')
      ? '<div class="sic-row"><span>' + label + '</span><b>' + esc(val) + '</b></div>' : '';
    const m = this._matchProjectDetail(data);
    const r = m.row || {};
    // 项目名用完整名（数据库完整 project_name，map_points 已导出完整）
    const fullName = (data.name || '') || (r.project_name) || (r.name) || '';
    let district, type, stage, date, summary;
    if (m.src === 'db') {
      // 数据库全字段（导出自 export_dashboard_db.py）→ 直接用数据自身
      district = data.district;
      type = data.project_type;
      stage = data.stage;
      date = data.publish_date;
      summary = data.ai_summary;
    } else if (m.src === 'workbuddy') {
      district = r.district || data.district;
      type = r.project_type || data.project_type;
      stage = r.status || data.stage;
      date = r.publish_date;
      summary = r.ai_summary;
    } else if (m.src === 'project_list') {
      district = data.district;
      type = r.type || data.project_type;
      stage = r.stage || data.stage;
      date = r.date;
      summary = r.ai_summary;
    } else {
      district = data.district;
      type = data.project_type;
      stage = data.stage;
    }
    let html = '';
    html += row('区县', district) + row('类型', type) + row('阶段', stage) + row('日期', date);
    // 重叠标注：同名重复（数据库未去重）+ 同坐标不同项目（视觉重叠），卡片里标出来
    let dupCount = 0, coordCount = 0;
    if (data.name || (data.value && data.value.length >= 2)) {
      const nk = String(data.name || '').trim();
      const ck = data.value && data.value.length >= 2
        ? Math.round(data.value[0] * 1e4) + ',' + Math.round(data.value[1] * 1e4) : null;
      const allPts = (window.DASHBOARD_DATA && window.DASHBOARD_DATA.map_points) || [];
      allPts.forEach(p => {
        if (!p) return;
        if (nk && String(p.name || '').trim() === nk) dupCount++;
        if (ck && p.value && p.value.length >= 2 &&
          Math.round(p.value[0] * 1e4) + ',' + Math.round(p.value[1] * 1e4) === ck) coordCount++;
      });
    }
    if (dupCount > 1) {
      html += '<div class="sic-row"><span>同名记录</span><b>共 ' + dupCount + ' 条</b></div>';
    }
    if (coordCount > 1) {
      html += '<div class="sic-row"><span>同坐标项目</span><b>' + coordCount + ' 个</b></div>';
    }
    if (summary) html += '<div class="sic-summary"><span>原文摘要</span><div>' + esc(summary) + '</div></div>';
    if (!this._infoCard) {
      this._infoCard = document.createElement('div');
      document.body.appendChild(this._infoCard);
    }
    this._infoCard.className = 'scatter-info-card compact ' + cls;   // compact：3D 图钉卡片保持原大小
    // 组内翻页导航（同坐标组合并：可翻看组内所有项目）
    let navHtml = '';
    if (memList) {
      navHtml =
        '<div class="sic-nav">' +
        '<button class="sic-nav-btn" data-dir="-1">‹</button>' +
        '<span class="sic-page">' + (curIdx + 1) + '/' + memList.length + '</span>' +
        '<button class="sic-nav-btn" data-dir="1">›</button>' +
        '</div>';
    }
    this._infoCard.innerHTML =
      '<div class="sic-head"><span class="sic-tag ' + cls + '">' + (data.warning || '预警') + '</span>' +
      '<button class="sic-close">×</button></div>' +
      '<div class="sic-name">' + esc(fullName) + '</div>' +
      navHtml +
      html +
      '<button class="sic-fly">详情</button>';
    this._infoCard.style.display = 'block';
    // 卡片定位到图标右侧（超出右边界则放左侧；左右边界都 clamp 防出屏）
    if (sx !== undefined) {
      const cw = 320, ch = 340;
      let left = sx + 34;
      let top = sy - ch / 2;
      const W = this.width || 1920, H = this.height || 1080;
      if (left + cw > W - 10) left = sx - cw - 34;
      left = Math.max(10, Math.min(left, W - cw - 10));
      top = Math.max(90, Math.min(top, H - ch - 60));
      this._infoCard.style.left = left + 'px';
      this._infoCard.style.top = top + 'px';
      this._infoCard.style.right = 'auto';
    }
    const closeBtn = this._infoCard.querySelector('.sic-close');
    const flyBtn = this._infoCard.querySelector('.sic-fly');
    if (closeBtn) closeBtn.onclick = () => this._hideScatterCard();
    // 传入完整匹配详情（含原数据，2D 里保留预警色/名称等基础字段）
    if (flyBtn) flyBtn.onclick = () => this._flyToStreet(lng, lat, { src: m.src, row: m.row, data: data });
    // 组内翻页：‹/› 切换同坐标组的其他项目（卡片位置不变）
    if (memList) {
      this._infoCard.querySelectorAll('.sic-nav-btn').forEach(btn => {
        btn.onclick = () => {
          const dir = parseInt(btn.getAttribute('data-dir'), 10);
          const ni = (curIdx + dir + memList.length) % memList.length;
          this._showScatterCard(memList[ni], sx, sy, memList, ni);
        };
      });
    }
  }

  _hideScatterCard(keepMode) {
    // keepMode=true：点击其他图钉切换目标（不恢复模式，保留 prevMode 供最终关闭时恢复）
    if (this._pinSolo) {
      this._pinSolo = null;
      if (!keepMode && this._focusPrevMode && this._focusPrevMode !== 'warning' && this._focusPrevMode !== this._mapMode) {
        const pm = this._focusPrevMode;
        this._focusPrevMode = null;
        this.setMapMode(pm);   // 恢复日志点击前的模式（如柱状图）
      } else if (!keepMode && this._mapMode === 'warning') {
        this._resetPins();     // 原模式就是预警图 → 恢复全部图钉（含颜色过滤）
      }
    }
    this._selectedPin = null;   // 关闭卡片 → 选中标签同时消失
    if (this._infoCard) this._infoCard.style.display = 'none';
  }

  // 从抓取日志点击：切预警图 + 选中标签 + 详情卡片（不动视角，立即弹出，无异步中断风险）
  focusWarningPin(q) {
    if (!q || !q.name) return false;
    const nm = String(q.name).trim();
    if (!nm) return false;
    if (this._mapMode !== 'warning') {
      this._focusPrevMode = this._mapMode;   // 记录日志点击前的模式（柱状图等），关闭独显时恢复
      this.setMapMode('warning');
    }
    if (!this._warningPinGroup || !this._warningPinGroup.visible) {
      console.warn('[focusWarningPin] 预警图钉组未就绪', this._mapMode, !!this._warningPinGroup);
      return false;
    }
    const ds = q.district || '';
    let target = null;
    this._warningPins.forEach(pg => {
      if (target) return;
      const d = pg.userData && pg.userData.data;
      if (!d) return;
      const pn = (d.name || '').trim();
      const nameHit = pn === nm || (nm.length > 4 && pn.indexOf(nm) === 0) || (nm.length > 4 && nm.indexOf(pn) === 0);
      if (nameHit) target = pg;   // 临时数据覆盖后区县字段可能不一致，仅按名称匹配
    });
    console.log('[focusWarningPin] mode:', this._mapMode, 'pins:', this._warningPins.length,
      'hit:', !!target, 'name:', nm, 'district:', ds);
    if (!target) { this._hideScatterCard(); return false; }
    // 独显模式：只显示选中的图钉，其余隐藏（关闭卡片/切模式/下钻时恢复全部）
    this._pinSolo = target;
    this._warningPins.forEach(pg => { pg.visible = (pg === target); });
    this._selectedPin = target;   // 选中标签常显（_animate 每帧投影；视野外自动隐藏）
    this._hoverPin = null;
    this._onScatterClick(target);   // 立即弹详情卡片（相机不动）
    return true;
  }

  // 查看街道：切到 2D 高德地图定位到该点街道级（可自由平移缩放查工业园/具体街道）
  // detail = { src, row, data }（完整字段，2D 里"展现所有的"）
  _flyToStreet(lng, lat, detail) {
    this._hideScatterCard();
    if (window.GaodeMap2D) {
      window.GaodeMap2D.show(lng, lat, 16, detail);
      return;
    }
    // 兜底：无 2D 模块时保留 3D 相机贴近
    this._street3dFallback(lng, lat);
  }

  // 进入 2D 前：捕获 3D 状态（返回时定位回选中区县）
  _captureFor2D() {
    this._returnState = {
      camPos: this.camera.position.clone(),
      target: this.controls.target.clone(),
      districtMode: this._districtMode,
      drillName: this._currentDrillName,
      mapMode: this._mapMode,
    };
    const mapEl = document.getElementById('map');
    if (mapEl) mapEl.style.display = 'none';
    this._hideScatterCard();
    this._updateDrillBackBtn();   // 进入 2D："返回 3D"按钮在位 → 隐藏"返回全市"
    // 2D 详情页：隐藏底部导航栏（详情页专属；返回 3D 时恢复，三个模式均有导航）
    const tray = document.querySelector('.bottom-tray');
    if (tray) tray.classList.add('tray-hidden');
    // 进入详情（2D）：hover 标签层挂在 body 上不随画布隐藏，需手动隐藏
    if (this._pinLabelLayer) this._pinLabelLayer.style.display = 'none';
    // 暂时隐藏大屏左右面板，中间地图+详情卡片占满
    const mb = document.querySelector('.mainbox');
    if (mb) mb.classList.add('detail-mode');
    // 2D 打开期间暂停 3D 渲染循环（隐藏画布每帧渲染白耗 CPU/GPU，还会拖慢 2D 与返回）
    if (this._rafId) {
      cancelAnimationFrame(this._rafId);
      this._rafId = null;
    }
    this._pausedFor2D = true;
  }

  // 从 2D 返回：恢复 3D 状态（显示画布 + 相机回位 → 定位回选中区县）
  _restoreFrom2D() {
    const mapEl = document.getElementById('map');
    if (mapEl) mapEl.style.display = '';
    if (this._returnState) {
      this.camera.position.copy(this._returnState.camPos);
      this.controls.target.copy(this._returnState.target);
      this.controls.update();
      this._returnState = null;
    }
    this._updateDrillBackBtn();   // 从 2D 返回：若恢复下钻状态则按钮同步显示
    if (this._pinLabelLayer) this._pinLabelLayer.style.display = '';   // 恢复 hover 标签层
    const tray = document.querySelector('.bottom-tray');
    if (tray) tray.classList.remove('tray-hidden');   // 恢复底部导航栏（3D 三个模式均有）
    const mb = document.querySelector('.mainbox');
    if (mb) mb.classList.remove('detail-mode');   // 恢复大屏左右面板
    // 瓦片刷新延迟 400ms：返回瞬间先让 3D 显示流畅，再按恢复视角拉瓦片（避免返回即拉几百张卡顿）
    clearTimeout(this._restoreTileTimer);
    this._restoreTileTimer = setTimeout(() => {
      this._lastWindowKey = '';
      this._refreshStreetWindow();
    }, 400);
    // 预警图：图钉淡入出场（从 2D 返回不走 _flyBackCity，直接出现没有动画，这里补上）
    if (this._mapMode === 'warning' && this._warningPinGroup && this._warningPinGroup.visible) {
      this._fadeInPins();
    }
    // 恢复 3D 渲染循环（_captureFor2D 暂停过）
    if (this._pausedFor2D) {
      this._pausedFor2D = false;
      this._rafId = requestAnimationFrame(this._animate);
    }
    // 2D 返回：统一刷新图表/柱状图/图钉（隐藏容器期间 echarts 渲染成 0 尺寸，
    // 必须重建；柱状图/图钉按当前周期刷新——修复"返回后区县预警数据/时间趋势空白、柱状图非本周"）
    setTimeout(() => {
      try { if (window.refreshAllCharts) window.refreshAllCharts(); } catch (e) {}
    }, 150);
  }

  _street3dFallback(lng, lat) {
    const [px, pyRaw] = this.geoProject([lng, lat]);
    const wx = px, wz = -pyRaw;
    const dist = 1.2, tilt = 0.55;
    const targetPos = new THREE.Vector3(wx, 0.2, wz);
    const camPos = new THREE.Vector3(wx, 0.2 + dist * Math.sin(tilt), wz + dist * Math.cos(tilt));
    this._windowAuto = true;   // 激活街道窗口（bar 模式也生效）
    this._lastWindowKey = '';
    // 预取街道瓦片：飞行期间加载，到达即显示（降低延迟）
    const preBbox = this._bboxForView(wx, wz, dist);
    const preZ = this._zoomFromDistance(dist);
    if (window.GaodeTiles) {
      window.GaodeTiles.fetchStitched(preBbox.minLng, preBbox.maxLng, preBbox.minLat, preBbox.maxLat, preZ, { maxTiles: 256 })
        .catch(() => null);
    }
    this._switching = true;
    this.controls.enabled = false;
    gsap.killTweensOf(this.camera.position);
    gsap.killTweensOf(this.controls.target);
    gsap.to(this.controls.target, { x: wx, y: 0.2, z: wz, duration: 1.6, ease: 'power3.inOut' });
    gsap.to(this.camera.position, {
      x: camPos.x, y: camPos.y, z: camPos.z,
      duration: 1.6, ease: 'power3.inOut',
      onComplete: () => {
        this._switching = false;
        this.controls.enabled = true;
        if (this._windowTimer) clearTimeout(this._windowTimer);
        this._windowTimer = setTimeout(() => this._refreshStreetWindow(), 200);
      },
    });
  }

  // ==================== 重建地图三层（挤出/顶面/描边），参数与初始创建一致 ====================
  _rebuildMapLayers(geojson) {
    if (this.extrudeMap) {
      this._disposeLayers(this.extrudeMap.mapGroup);
      if (this.extrudeMap.mapGroup.parent) this.extrudeMap.mapGroup.parent.remove(this.extrudeMap.mapGroup);
    }
    if (this.baseMap) {
      this._disposeLayers(this.baseMap.mapGroup);
      if (this.baseMap.mapGroup.parent) this.baseMap.mapGroup.parent.remove(this.baseMap.mapGroup);
    }
    if (this.borderLine) {
      this._disposeLayers(this.borderLine.lineGroup);
      if (this.borderLine.lineGroup.parent) this.borderLine.lineGroup.parent.remove(this.borderLine.lineGroup);
    }

    const spaced = this._shrinkPolygons(geojson);

    const extrude = new ExtrudeMap(this.geoProject, {
      data: spaced,
      depth: this.depth,
      topFaceMaterial: this._topMat,
      sideMaterial: this.sideMaterial,
      position: new THREE.Vector3(0, 0, 0.11),
      renderOrder: 9,
    });
    extrude.setParent(this.focusMapGroup);
    this.extrudeMap = extrude;
    this.coordinates = extrude.getCoordinates();

    const baseMap = new BaseMap(this.geoProject, {
      data: spaced,
      merge: false,
      material: this._faceMat,
      position: new THREE.Vector3(0, 0, this.depth + 0.22),
      renderOrder: 2,
    });
    baseMap.setParent(this.focusMapGroup);
    this.baseMap = baseMap;

    const line = new Line(this.geoProject, {
      data: spaced,
      type: 'Line3',
      material: this._strokeMat,
      tubeRadius: 0.1,
      position: new THREE.Vector3(0, 0, this.depth + 0.24),
      renderOrder: 22,
    });
    line.setParent(this.focusMapGroup);
    this.borderLine = line;

    // 刷新交互面：移除旧顶面 mesh（保留柱子等），重新收集
    this.intersectMeshes = this.intersectMeshes.filter(m => !m.userData.isMapFace);
    baseMap.mapGroup.traverse((child) => {
      if (child.isMesh) {
        child.userData.isMapFace = true;
        this.intersectMeshes.push(child);
      }
    });
  }

  // 释放几何体（材质是共享实例，不 dispose）
  _disposeLayers(group) {
    if (!group) return;
    group.traverse((child) => {
      if (child.geometry) child.geometry.dispose();
    });
  }

  // ==================== 自适应 ====================
  resize() {
    // 始终使用容器尺寸（autofit 固定为 1920×1080），不跟随 window 变化
    this.width = this.container.clientWidth || window.innerWidth;
    this.height = this.container.clientHeight || window.innerHeight;
    this.camera.aspect = this.width / this.height;
    this.camera.updateProjectionMatrix();
    this.renderer.setSize(this.width, this.height);
    if (this.label3d && this.label3d.sizes) {
      this.label3d.sizes.width = this.width;
      this.label3d.sizes.height = this.height;
    }
  }

  // ==================== 销毁 ====================
  /**
   * 重新加载预警点位（数据更新后调用：图钉 + 标签 + 2D 标记全量重建）
   * 散点（Sprite）已弃用；柱状图由 refreshAllCharts 的 updateBars 更新
   */
  reloadPoints() {
    if (this._warningPinGroup) {
      this._disposeLayers(this._warningPinGroup);
      if (this._warningPinGroup.parent) this._warningPinGroup.parent.remove(this._warningPinGroup);
      this._warningPinGroup = null;
      this._warningPins = [];
      this._dupGroups = new Map();
    }
    if (this._pinLabelLayer) this._pinLabelLayer.innerHTML = '';   // 清空旧图钉标签
    if (this._yantaiGeojson) this._addWarningPins();
    if (this._warningPinGroup) {
      this._warningPinGroup.visible = (this._mapMode === 'warning');
      if (this._mapMode === 'warning') this.setPinPeriod(this._pinPeriod);
    }
    // 2D 地图标记同步刷新
    if (window.GaodeMap2D && typeof window.GaodeMap2D.refreshMarkers === 'function') {
      window.GaodeMap2D.refreshMarkers();
    }
  }

  destroy() {
    this.isDestroyed = true;
    cancelAnimationFrame(this._rafId);
    // 移除交互监听
    if (this.renderer && this.renderer.domElement) {
      if (this._onPointerMoveB) this.renderer.domElement.removeEventListener('pointermove', this._onPointerMoveB);
      if (this._onPointerDownB) this.renderer.domElement.removeEventListener('pointerdown', this._onPointerDownB);
      if (this._onClickB) this.renderer.domElement.removeEventListener('click', this._onClickB);
    }
    if (this.focus) { this.focus.destroy(); }
    if (this.label3d) { this.label3d.destroy(); }
    this._stopWindowAutoRefresh();
    if (this._restoreTileTimer) { clearTimeout(this._restoreTileTimer); this._restoreTileTimer = null; }
    if (this.controls) {
      if (this._windowChangeB) this.controls.removeEventListener('change', this._windowChangeB);
      this.controls.dispose();
    }
    if (this._warningPinGroup) {
      this._disposeLayers(this._warningPinGroup);
      if (this._warningPinGroup.parent) this._warningPinGroup.parent.remove(this._warningPinGroup);
      this._warningPinGroup = null;
      this._warningPins = [];
    }
    if (this._pinTimer) { clearTimeout(this._pinTimer); this._pinTimer = null; }
    if (this._hoverTimer) { clearTimeout(this._hoverTimer); this._hoverTimer = null; }
    if (this._drillBackBtn && this._drillBackBtn.parentNode) {
      this._drillBackBtn.parentNode.removeChild(this._drillBackBtn);
      this._drillBackBtn = null;
    }
    if (this._pinLabelLayer && this._pinLabelLayer.parentNode) {
      this._pinLabelLayer.parentNode.removeChild(this._pinLabelLayer);
      this._pinLabelLayer = null;
    }
    if (this._infoCard && this._infoCard.parentNode) {
      this._infoCard.parentNode.removeChild(this._infoCard);
    }
    this.scene.traverse((child) => {
      if (child.geometry) child.geometry.dispose();
      if (child.material) {
        if (Array.isArray(child.material)) {
          child.material.forEach(m => { if (m.map) m.map.dispose(); m.dispose(); });
        } else {
          if (child.material.map) child.material.map.dispose();
          child.material.dispose();
        }
      }
    });
    this.renderer.dispose();
    if (this.renderer.domElement && this.renderer.domElement.parentNode) {
      this.renderer.domElement.parentNode.removeChild(this.renderer.domElement);
    }
    const cssDom = this.container.querySelector('[class^="label3d-"]');
    if (cssDom && cssDom.parentNode) cssDom.parentNode.removeChild(cssDom);
    this.intersectMeshes = [];
    this.scatterItems = [];
  }
}

export { YantaiMap3D };
