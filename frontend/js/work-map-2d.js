// ============================================================
// 施工图 2D 地图（高德 JS API 独立模块，与预警图 Leaflet 彻底隔离）
// 底图 features:['bg','road'] —— 保留全部街道名、无商店 POI
// 暴露 window.WorkMap2D：show(lng,lat,zoom) / hide / isVisible
// 容器 #workmap2d（独立，不占用 Leaflet 的 #map2d）
// ============================================================
(function () {
  'use strict';

  var AMAP_KEY = 'abe1b4450af643a9c255327f16de0ade';
  var map = null;
  var loadingPromise = null;
  var roadOverlays = [];
  var visible = false;

  // ---------- SVG 点击层（道路热区 DOM 层，不依赖 AMap 覆盖物事件） ----------
  // 在地图容器上叠一个透明 SVG：每条道路画一条宽描边透明 path（视觉=沿路细长矩形），
  // click 直接绑 SVG path 元素（纯 DOM，缩放/移动由容器事件重算，绝对可靠）
  var hitSvg = null;
  var hitPaths = [];          // [{ path: <SVGPathElement>, r: <road> }]
  var hitRepaint = null;      // 防抖重绘

  function ensureHitSvg() {
    var el = document.getElementById('workmap2d');
    if (!el || hitSvg) return;
    var ns = 'http://www.w3.org/2000/svg';
    hitSvg = document.createElementNS(ns, 'svg');
    hitSvg.setAttribute('style',
      'position:absolute; inset:0; width:100%; height:100%; ' +
      'pointer-events:none; z-index:66;');   // 容器层只响应子 path（各自 pointer-events:stroke）
    el.appendChild(hitSvg);
    // 地图视角变化（拖动/缩放/动画）后重绘热区位置
    if (map && !map.__hitBound) {
      map.__hitBound = true;
      ['moveend', 'zoomend'].forEach(function (ev) {
        map.on(ev, function () { scheduleHitRepaint(); });
      });
    }
  }
  function clearHitSvg() {
    if (hitSvg) {
      hitSvg.innerHTML = '';
      hitSvg = null;
    }
    hitPaths = [];
  }
  function scheduleHitRepaint() {
    if (hitRepaint) return;
    hitRepaint = setTimeout(function () {
      hitRepaint = null;
      repaintHits();
    }, 60);   // 防抖：拖动结束才重绘
  }
  // 当前视野重画所有热区 path（用 lngLatToContainer 投影到像素）
  function repaintHits() {
    if (!map || !hitSvg || !hitPaths.length) return;
    var ns = 'http://www.w3.org/2000/svg';
    hitPaths.forEach(function (hp) {
      var pts = hp.pathPoints || [];
      if (pts.length < 2) { hp.path.setAttribute('d', ''); return; }
      var d = '';
      pts.forEach(function (p, i) {
        var c = map.lngLatToContainer(new AMap.LngLat(p[0], p[1]));
        if (c && isFinite(c.x) && isFinite(c.y)) {
          d += (i === 0 ? 'M' : 'L') + c.x.toFixed(1) + ',' + c.y.toFixed(1) + ' ';
        }
      });
      hp.path.setAttribute('d', d);
    });
  }
  // 绑定一条道路的 SVG 热区（DOM click）
  function bindRoadSvgHit(entry) {
    ensureHitSvg();
    if (!hitSvg) return;
    var ns = 'http://www.w3.org/2000/svg';
    var p = document.createElementNS(ns, 'path');
    p.setAttribute('fill', 'none');
    p.setAttribute('stroke', 'rgba(255,255,255,0.01)');   // 几乎透明（几乎不可见），可点击
    p.setAttribute('stroke-width', '30');                  // 宽描边 = 沿路"细长矩形"热区
    p.setAttribute('stroke-linecap', 'round');             // 端点圆头（端点也可点）
    p.setAttribute('style', 'pointer-events:stroke; cursor:pointer;');
    p.addEventListener('click', function (ev) {
      ev.stopPropagation();
      selectRoad(entry.r);
    });
    hitSvg.appendChild(p);
    hitPaths.push({ path: p, r: entry.r, pathPoints: entry.path });
    p.__pathPoints = entry.path;
    repaintHits();
  }
  var lastActiveR = null;   // 当前选中道路：规划完成后若仍是它 → 重新定位跟随（防"定位后看不到线"）
  var pendingRoad = null;   // 地图未就绪时点击列表暂存的道路 → 地图创建后自动定位+弹卡
  var pendingDistrict = ''; // 地图未就绪时点击的区县 → 地图创建后自动定位
  // 定位到某区县全部道路（列表/地图通用）
  function fitDistrictRoads(name) {
    var roads = getWorkRoads().filter(function (r) { return wDistrictMatch(name, r); });
    fitRoads(roads);
  }
  // 统一道路选中动作：平滑下钻推近到整条路（有动画），动画结束后弹详情
  // 有坐标 → 偏置 fit（道路在中偏右，卡片完整落在中右区）；
  // 无坐标 → 镜头移到所属区县中心（模糊位置提示），卡片弹区县中心
  function selectRoad(r) {
    if (!r) return;
    if (!map) { pendingRoad = r; console.log('[施工图] 地图加载中，稍后就绪后自动定位: ' +
      (r.road || r.name || '')); return; }
    lastActiveR = r;
    if (roadEntryPath(r)) {
      fitRoads([r]);              // 居中 fit（锚点=路径中心 → 卡片居中）
    } else {
      var dc = districtCenterOf(r);
      if (dc) map.setZoomAndCenter(11, dc);   // 无坐标：飞到区县中心
    }
    openCardAfterMove(r, true);   // 动画结束（moveend）再弹卡，稳居屏幕中间
  }
  // 外部聚焦一条施工道路（底部抓取日志点击等）：2D 未显示 → 自动打开 2D（按该区县列表加载），
  // 地图就绪后走 pendingRoad 机制自动定位 + 弹详情卡
  function focusRoad(r) {
    if (!r) return;
    var el = document.getElementById('workmap2d');
    var shown = !!(el && el.style.display !== 'none' && map);
    if (shown) { selectRoad(r); return; }
    pendingRoad = r;
    var s = r.start, e = r.end;
    var hasGeo = !!(s && e && s.length >= 2 && e.length >= 2);
    var c = hasGeo
      ? [(s[0] + e[0]) / 2, (s[1] + e[1]) / 2]
      : (districtCenterOf(r) || [120.78, 37.25]);
    show(c[0], c[1], 11, null, r.district || '');
  }
  function updateSvgHitPoints(entry) {
    hitPaths.forEach(function (hp) {
      if (hp.r === entry.r) { hp.pathPoints = entry.path; hp.path.__pathPoints = entry.path; }
    });
    scheduleHitRepaint();
  }

  // 高德安全密钥（2021-12 后申请的 key 服务调用必须配 jscode，否则 Driving 等报 error）
  // 官方要求：必须在加载 JS API 的 <script> 之前设置
  var AMAP_SECURITY_CODE = '7996d7e7b10e7fab09fa481cadbe2194';
  // ---------- 高德 JS API 懒加载（含路线规划插件 AMap.Driving） ----------
  function loadAmap() {
    if (!loadingPromise) {
      loadingPromise = new Promise(function (resolve, reject) {
        // 安全密钥必须在 script 加载前设置（若已设则保留用户配置）
        if (!window._AMapSecurityConfig) {
          window._AMapSecurityConfig = { securityJsCode: AMAP_SECURITY_CODE };
        }
        var s = document.createElement('script');
        // plugin=AMap.Driving：路线规划（施工道路沿真实路网，非两点直线）
        s.src = 'https://webapi.amap.com/maps?v=2.0&key=' + AMAP_KEY + '&plugin=AMap.Driving';
        s.onload = function () {
          if (window.AMap) resolve();
          else reject(new Error('AMap 未就绪'));
        };
        s.onerror = function () { reject(new Error('高德 JS API 加载失败（检查 key/网络）')); };
        document.head.appendChild(s);
      }).catch(function (e) {
        loadingPromise = null;
        throw e;
      });
    }
    return loadingPromise;
  }
  // 确保路线规划插件可用（Driving 驾车 + Walking 步行兜底；插件异步就绪，逐批 AMap.plugin）
  function ensureRouteApis() {
    return loadAmap().then(function () {
      function one(name) {
        return new Promise(function (resolve) {
          if (window.AMap && AMap[name]) return resolve();
          AMap.plugin(['AMap.' + name], function () { resolve(); });
        });
      }
      return Promise.all([one('Driving'), one('Walking')]);
    });
  }

  // ---------- 级别 → 颜色（备用；干线红/骨干橙/其他黄） ----------
  function roadLevelColor(level) {
    var lv = String(level || '').trim();
    // level 字段兼容两种写法：语义（干线/骨干汇聚/其他）与字面色（红/橙/黄）
    if (lv.indexOf('干线') >= 0 || lv.indexOf('红') >= 0) return '#ff385c';
    if (lv.indexOf('骨干') >= 0 || lv.indexOf('汇聚') >= 0 || lv.indexOf('橙') >= 0) return '#ff8a3d';
    return '#ffd23d';
  }
  // ---------- 施工状态 → 颜色（主视觉：管理者一眼看出状态） ----------
  // 施工中=绿 / 已完工=灰 / 未开工=黄 / 暂停施工=红；未知兜底蓝
  function roadStatusColor(status) {
    var s = String(status || '').trim();
    if (s.indexOf('施工中') >= 0) return '#22c55e';
    if (s.indexOf('已完工') >= 0) return '#9ca3af';
    if (s.indexOf('未开工') >= 0) return '#facc15';
    if (s.indexOf('暂停') >= 0) return '#ef4444';
    return '#60a5fa';
  }

  // ---------- 道路线绘制（双线光晕 + 圆点） ----------
  // 注意：不用 Polyline/CircleMarker 自身的 click 事件——高德官方历史 bug：
  // "path 含同经/同纬度时事件无法触发"（水平/垂直道路命中），拾取不稳定。
  // 改用地图级 click + 点到线段距离判定（官方保证 map.click 一定触发，最稳）。
  var roadData = [];   // 每帧同步：绘制时记录 {r, s, e}，供地图 click 判定
  function addRoadLines() {
    clearRoadLines();
    var roads = getWorkRoads();   // 周期过滤后的一次全量（直线即时显示，弯曲异步替换）
    if (!map || !roads.length) return;
    roadData = [];

    roads.forEach(function (r) {
      var s = r && r.start, e = r && r.end;
      if (!s || !e || s.length < 2 || e.length < 2) return;
      // 主视觉 = 施工状态色（管理者一眼看出：施工中绿/已完工灰/未开工黄/暂停红）
      var color = roadStatusColor(r.status);
      // 坐标与标注长度严重矛盾（coord_conflict，如标注 0.2km 但坐标跨 24km）：
      // 不拉与描述不符的假长线 → 以"中点施工点"圆点呈现，卡片提示核对数据
      if (r.coord_conflict) {
        var midC = [(s[0] + e[0]) / 2, (s[1] + e[1]) / 2];
        var centry = { r: r, path: [midC.slice(), midC.slice()] };   // 同点 path → 点工程 z15 定位
        roadData.push(centry);
        drawPointMarker(r, midC, color);
        return;
      }
      var straight = [[s[0], s[1]], [e[0], e[1]]];      // 直线兜底（[lng,lat]）
      var entry = { r: r, path: straight.slice() };      // 当前显示路径点（可被真实路线替换）
      roadData.push(entry);

      function lngLatArr(pts) {
        return pts.map(function (p) { return new AMap.LngLat(p[0], p[1]); });
      }
      // 状态色宽带（不透明覆盖底图黄路：高德 road 要素道路是黄色，若半透明会透出黄 → 视觉与状态色不一致）
      var glow = new AMap.Polyline({
        path: lngLatArr(straight),
        strokeColor: color,
        strokeWeight: 24,
        strokeOpacity: 0.95,   // 高不透明度盖住底图黄色道路
        zIndex: 50,
      });
      glow.setMap(map);
      roadOverlays.push(glow);

      // 细芯线 = 级别色（干线红 / 骨干汇聚橙 / 其他黄），叠在状态色光晕带上
      var line = new AMap.Polyline({
        path: lngLatArr(straight),
        strokeColor: roadLevelColor(r.level),
        strokeWeight: 4,
        strokeOpacity: 0.9,
        zIndex: 52,
      });
      line.setMap(map);
      roadOverlays.push(line);

      // 端点视觉圆点（HTML Marker，仅显示；点击走 SVG 热区）
      function addDot(lnglat) {
        var dot = document.createElement('div');
        dot.className = 'work-hitdot';
        dot.style.background = color;
        dot.style.boxShadow = '0 0 8px ' + color;
        dot.style.pointerEvents = 'none';   // 不拦截点击，让 SVG 热区统一处理
        var mk = new AMap.Marker({
          position: lnglat,
          content: dot,
          offset: new AMap.Pixel(-8, -8),
          zIndex: 65,
        });
        mk.setMap(map);
        roadOverlays.push(mk);
        return mk;
      }
      var dotStart = addDot(new AMap.LngLat(s[0], s[1]));
      var dotEnd = addDot(new AMap.LngLat(e[0], e[1]));

      // SVG 点击热区：整条路一条宽描边透明 path（纯 DOM 点击，绝对可靠）
      bindRoadSvgHit(entry);

      // 异步获取真实道路路径（多级回退规划），成功后更新线 + 端点 + SVG 热区
      fetchRoadRoute(r, function (routePts) {
        if (!routePts || !map) {
          // 规划全败：零长度段（<100m）画施工圆点标记（Polyline 不可见，圆点任何 zoom 可见）
          if (routePts === null && shortDotKeys[roadKey(s, e)]) drawPointMarker(r, s, color);
          return;
        }
        // 防御：过滤范围外/异常路径点（防引擎混入 (0,0) 等把线画出中国/锚点算飞）
        routePts = routePts.filter(function (p) {
          return isFinite(p[0]) && isFinite(p[1]) && p[0] > 100 && p[0] < 130 && p[1] > 20 && p[1] < 45;
        });
        if (routePts.length < 2) {
          if (shortDotKeys[roadKey(s, e)]) drawPointMarker(r, s, color);   // 过滤后不可画 → 施工圆点
          return;
        }
        entry.path = routePts;
        var ll = lngLatArr(routePts);
        glow.setPath(ll);
        line.setPath(ll);
        // 端点随真实路径首尾移动
        if (dotStart) dotStart.setPosition(ll[0]);
        if (dotEnd) dotEnd.setPosition(ll[ll.length - 1]);
        // SVG 热区路径点同步 + 重绘
        hitPaths.forEach(function (hp) {
          if (hp.r === r) { hp.pathPoints = routePts; }
        });
        scheduleHitRepaint();
        // 规划吸附可能偏离原始坐标几百米：若用户此刻正选中这条路，
        // 重新定位跟随真实路径（否则屏幕停在原地 → "看不到这条路"）；
        // 卡片还开着则随新路径重新居中
        if (lastActiveR === r) {
          setTimeout(function () {
            fitRoads([r]);
            openCardAfterMove(r, false);
          }, 80);
        }
      });
    });
    bindMapRoadClick();
    scheduleHitRepaint();   // 初次绘制完统一投影一次
  }

  // 点到折线路径最短距离（经纬度平面近似；烟台范围小，误差可忽略）
  // entry.path = [[lng,lat], ...]；遍历每段求最短（端点自然包含）
  function distToRoad(lng, lat, path) {
    if (!path || path.length < 2) return Infinity;
    function segDist(px, py, ax, ay, bx, by) {
      var dx = bx - ax, dy = by - ay;
      var len2 = dx * dx + dy * dy;
      var t = len2 > 0 ? ((px - ax) * dx + (py - ay) * dy) / len2 : 0;
      t = Math.max(0, Math.min(1, t));
      var qx = ax + t * dx, qy = ay + t * dy;
      return Math.sqrt((px - qx) * (px - qx) + (py - qy) * (py - qy));
    }
    var best = Infinity;
    for (var i = 0; i < path.length - 1; i++) {
      var d = segDist(lng, lat, path[i][0], path[i][1], path[i + 1][0], path[i + 1][1]);
      if (d < best) best = d;
    }
    return best;
  }

  // ---------- 施工圆点标记（起终点 <100m 且规划全败：零长度线不可见 → 醒目大圆点） ----------
  var dotMarkers = [];   // {r, lng, lat}
  function drawPointMarker(r, pos, color) {
    if (!map || !r || !pos) return;
    var dot = document.createElement('div');
    dot.className = 'work-ptdot';
    dot.style.background = color;
    dot.style.boxShadow = '0 0 12px ' + color + ', 0 0 4px rgba(255,255,255,.8)';
    dot.style.pointerEvents = 'none';   // 点击走地图级判定（与道路线一致）
    var mk = new AMap.Marker({
      position: new AMap.LngLat(pos[0], pos[1]),
      content: dot,
      offset: new AMap.Pixel(-12, -12),
      zIndex: 68,
    });
    mk.setMap(map);
    roadOverlays.push(mk);
    dotMarkers.push({ r: r, lng: pos[0], lat: pos[1] });
  }

  // 地图级点击：命中最近的道路/圆点（距离阈值按 zoom 换算：≈ 屏幕 14px 对应经纬度）
  // 点击道路/端点 → 拉近到该项目 + 弹详情窗
  function bindMapRoadClick() {
    if (!map || map.__roadClickBound) return;
    map.__roadClickBound = true;
    map.on('click', function (e) {
      if (!roadData.length && !dotMarkers.length) return;
      var lng = e.lnglat.getLng(), lat = e.lnglat.getLat();
      var zoom = map.getZoom() || 15;
      var spanPerPx = 0.3 / Math.pow(2, zoom - 15) / 1000;   // 粗略：z15 0.3° / 1000px
      var threshold = spanPerPx * 14;   // ≈ 14px
      var best = null, bestD = threshold;
      roadData.forEach(function (rd) {
        var d = distToRoad(lng, lat, rd.path);
        if (d < bestD) { bestD = d; best = rd; }
      });
      // 圆点标记命中（容差放宽 ~22px：圆点本身 24px）
      var dotTh = threshold * 1.8;
      var bestDot = null, bestDotD = dotTh;
      dotMarkers.forEach(function (dm) {
        var d = Math.sqrt((lng - dm.lng) * (lng - dm.lng) + (lat - dm.lat) * (lat - dm.lat));
        if (d < bestDotD) { bestDotD = d; bestDot = dm; }
      });
      if (bestDot && (!best || bestDotD < bestD)) best = { r: bestDot.r };
      if (best) {
        selectRoad(best.r);   // 统一选中动作（含地图未就绪暂存）
      } else if (roadCardOpen()) {
        hideRoadCard();   // 点击地图空白 → 关闭固定详情卡
      }
    });
  }

  // ---------- 真实道路路径获取（路线规划；缓存 + 并发队列 + Driving→Walking 双引擎回退） ----------
  // 施工点位很多不在可驾车路网上（路侧/村里/管沟口）→ Driving error；回退 Walking 会吸附到最近
  // 道路（人行道沿市政道路线，与车行线几乎重合），两者都失败才画直线兜底。
  // 并发最多 4 个（一次性 55 并发易触发限流）；结果缓存 → 跨区县重画零请求、二次进入秒弯曲。
  var routeCache = {};
  var planQueue = [];          // 待规划队列 {r, done}
  var planRunning = 0;
  var MAX_PLAN_RUN = 4;
  var shortDotKeys = {};       // 起终点 <100m 且规划全败的路（key → true）：画施工圆点标记

  function roadKey(s, e) {
    return s[0].toFixed(5) + ',' + s[1].toFixed(5) + '>' + e[0].toFixed(5) + ',' + e[1].toFixed(5);
  }
  function fetchRoadRoute(r, done) {
    var s = r && r.start, e = r && r.end;
    if (!s || !e || s.length < 2 || e.length < 2) { done(null); return; }
    var key = roadKey(s, e);
    if (routeCache[key]) { done(routeCache[key]); return; }   // 缓存命中 → 同步给路径点
    ensureRouteApis().then(function () {                      // 插件未就绪前入队等待
      planQueue.push({ r: r, key: key, done: done });
      planNext();
    });
  }
  function planNext() {
    while (planRunning < MAX_PLAN_RUN && planQueue.length) {
      var job = planQueue.shift();
      planRunning++;
      doPlan(job.r, job.key, function (pts) {
        planRunning--;
        job.done(pts);
        planNext();
      });
    }
  }
  // 提取高德首个路线全部 step.path 折线点（Driving/Walking 结构一致）+ 去重相邻点
  function extractRoute(result) {
    if (!result || !result.routes || !result.routes.length) return null;
    var route = result.routes[0];
    var pts = [];
    (route.steps || []).forEach(function (st) {
      (st.path || []).forEach(function (p) {
        if (p && p.lng !== undefined) pts.push([p.lng, p.lat]);
      });
    });
    var clean = [];
    pts.forEach(function (p) {
      var last = clean[clean.length - 1];
      if (!last || last[0] !== p[0] || last[1] !== p[1]) clean.push(p);
    });
    return clean.length >= 2 ? clean : null;
  }
  function dedupPts(pts) {
    var clean = [];
    pts.forEach(function (p) {
      var last = clean[clean.length - 1];
      if (!last || last[0] !== p[0] || last[1] !== p[1]) clean.push(p);
    });
    return clean;
  }
  // 两点直线跨度（km，1°≈101km 近似）
  function spanKm(a, b) {
    var dx = a[0] - b[0], dy = a[1] - b[1];
    return Math.sqrt(dx * dx + dy * dy) * 101;
  }
  // 沿 a→b 连线把 a 向反方向外延 dMeters 米（b 点同理）→ 高速"接入点外扩"候选
  function extendPoint(a, b, dMeters) {
    var dx = b[0] - a[0], dy = b[1] - a[1];
    var len = Math.sqrt(dx * dx + dy * dy) || 1e-9;
    var cosLat = Math.max(0.5, Math.cos(a[1] * Math.PI / 180));
    return [
      a[0] - (dx / len) * dMeters / (101000 * cosLat),
      a[1] - (dy / len) * dMeters / 101000,
    ];
  }
  function lerpPt(a, b, t) {
    return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t];
  }

  // ==================== OSRM 公共路由兜底（开源引擎，无高德导航限制） ====================
  // 高德导航引擎拒绝高速主线起终点/乡道无路网；OSRM 把起终点 snap 到最近路（含高速/乡村路）。
  // 注意坐标系：OSRM(OSM)=WGS84，高德底图=GCJ-02 → 返回点集必须 wgs2gcj 纠偏后再画。
  // 公共实例在欧洲（router.project-osrm.org），国内网络可能慢 → 4s 超时，失败静默直线。
  var OSRM_BASE = 'https://router.project-osrm.org/route/v1/driving/';
  function fetchOsrm(s, e, done) {
    var url = OSRM_BASE + s[0] + ',' + s[1] + ';' + e[0] + ',' + e[1] +
      '?overview=full&geometries=polyline&steps=false&alternatives=false';
    var timedOut = false;
    var timer = setTimeout(function () { timedOut = true; done(null, 'timeout'); }, 4000);
    fetch(url).then(function (res) { return res.json(); }).then(function (j) {
      if (timedOut) return;
      clearTimeout(timer);
      if (!j || j.code !== 'Ok' || !j.routes || !j.routes.length) {
        done(null, (j && j.code) || 'err');
        return;
      }
      var pts = decodePolyline6(j.routes[0].geometry);
      if (pts.length < 2) { done(null, 'nodata'); return; }
      done(pts.map(function (p) { return wgs2gcj(p[0], p[1]); }), null);
    }).catch(function () {
      if (timedOut) return;
      clearTimeout(timer);
      done(null, 'network');
    });
  }
  // polyline6 解码（OSRM geometry 编码格式）
  function decodePolyline6(str) {
    var pts = [], idx = 0, len = str.length, lat = 0, lng = 0;
    while (idx < len) {
      var b, shift = 0, result = 0;
      do { b = str.charCodeAt(idx++) - 63; result |= (b & 0x1f) << shift; shift += 5; } while (b >= 0x20);
      lat += (result & 1) ? ~(result >> 1) : (result >> 1);
      shift = 0; result = 0;
      do { b = str.charCodeAt(idx++) - 63; result |= (b & 0x1f) << shift; shift += 5; } while (b >= 0x20);
      lng += (result & 1) ? ~(result >> 1) : (result >> 1);
      pts.push([lng * 1e-6, lat * 1e-6]);
    }
    return pts;
  }
  // WGS84 → GCJ-02 坐标纠偏（标准算法，画到高德底图前必须用）
  var _a = 6378245.0, _ee = 0.00669342162296594323;
  function _tLat(x, y) {
    var r = -100 + 2 * x + 3 * y + 0.2 * y * y + 0.1 * x * y + 0.2 * Math.sqrt(Math.abs(x));
    r += (20 * Math.sin(6 * x * Math.PI) + 20 * Math.sin(2 * x * Math.PI)) * 2 / 3;
    r += (20 * Math.sin(y * Math.PI) + 40 * Math.sin(y / 3 * Math.PI)) * 2 / 3;
    r += (160 * Math.sin(y / 12 * Math.PI) + 320 * Math.sin(y * Math.PI / 30)) * 2 / 3;
    return r;
  }
  function _tLng(x, y) {
    var r = 300 + x + 2 * y + 0.1 * x * x + 0.1 * x * y + 0.1 * Math.sqrt(Math.abs(x));
    r += (20 * Math.sin(6 * x * Math.PI) + 20 * Math.sin(2 * x * Math.PI)) * 2 / 3;
    r += (20 * Math.sin(x * Math.PI) + 40 * Math.sin(x / 3 * Math.PI)) * 2 / 3;
    r += (150 * Math.sin(x / 12 * Math.PI) + 300 * Math.sin(x / 30 * Math.PI)) * 2 / 3;
    return r;
  }
  function wgs2gcj(lng, lat) {
    var dLat = _tLat(lat - 35.0, lng - 105.0);
    var dLng = _tLng(lat - 35.0, lng - 105.0);
    var radLat = lat / 180 * Math.PI;
    var magic = Math.sin(radLat);
    magic = 1 - _ee * magic * magic;
    var sqrtMagic = Math.sqrt(magic);
    dLat = (dLat * 180) / ((_a * (1 - _ee)) / (magic * sqrtMagic) * Math.PI);
    dLng = (dLng * 180) / (_a / sqrtMagic * Math.cos(radLat) * Math.PI);
    return [lng + dLng, lat + dLat];
  }

  // ==================== 主规划链（多级回退，全失败才直线/圆点） ====================
  // 层级: Driving → Driving反向 → Walking(≤8km) → Walking反向 → 高速外扩 → 长路分段 → OSRM
  function doPlan(r, key, done) {
    var s = r.start, e = r.end;
    var name = r.road || r.name || '?';
    var distKm = spanKm(s, e);
    var isHighway = /高速|沈海|荣乌|烟海|立交/.test(name);
    var log = function (msg) { console.log('[施工图] ' + name + ' ' + msg); };

    // ---- 高德引擎单次规划（dir=-1 时起终点对调，防方向性偶发失败） ----
    function amapSearch(engine, dir, cb) {
      var o = dir < 0 ? e : s, d = dir < 0 ? s : e;
      var api;
      try {
        api = (engine === 'Driving')
          ? new AMap.Driving({ policy: AMap.DrivingPolicy.LEAST_TIME })
          : new AMap.Walking();
      } catch (err) {
        console.error('[施工图] ' + engine + ' 初始化失败:', err);
        cb(null);
        return;
      }
      api.search(new AMap.LngLat(o[0], o[1]), new AMap.LngLat(d[0], d[1]), function (status, result) {
        var pts = (status === 'complete') ? extractRoute(result) : null;
        if (pts) {
          var r0 = result.routes[0];
          log(engine + (dir < 0 ? '(反向)' : '') + ' status=complete OK | steps=' +
            (r0.steps || []).length + ' 路径点=' + pts.length);
          cb(pts);
          return;
        }
        var em = '';
        if (result) em = result.info || result.message || result.code || '';
        log(engine + (dir < 0 ? '(反向)' : '') + ' 失败 status=' + status + ' info=' +
          (em || '（无错误信息）') + (status === 'no_data' ? ' —— 起/终点附近无路网' : ''));
        cb(null);
      });
    }
    // ---- 高速接入点外扩：沿连线向两端外延采样"可上车点"，让引擎从互通上高速 ----
    function tryExtend(cb) {
      var candA = [extendPoint(s, e, 500), extendPoint(s, e, 1500)];
      var candB = [extendPoint(e, s, 500), extendPoint(e, s, 1500)];
      var tried = 0;
      (function nextCombo() {
        var ai = Math.floor(tried / 2), bi = tried % 2;
        if (tried >= 4) { log('高速外扩 4 组候选均失败 → 下阶段'); cb(null); return; }
        tried++;
        log('高速外扩尝试 起点外延' + [500, 1500][ai] + 'm × 终点外延' + [500, 1500][bi] + 'm');
        var oa = candA[ai], ob = candB[bi];
        var driving;
        try {
          driving = new AMap.Driving({ policy: AMap.DrivingPolicy.LEAST_TIME });
        } catch (err) {
          log('高速外扩 Driving 初始化失败 → 下一候选');
          nextCombo();
          return;
        }
        driving.search(new AMap.LngLat(oa[0], oa[1]), new AMap.LngLat(ob[0], ob[1]),
          function (status, result) {
            var pts = (status === 'complete') ? extractRoute(result) : null;
            if (pts) {
              log('高速外扩 OK | 路径点=' + pts.length + '（含互通连接线，视觉=真实高速走向）');
              cb(pts);
              return;
            }
            var em = '';
            if (result) em = result.info || result.message || result.code || '';
            log('高速外扩 失败 status=' + status + ' info=' + (em || '（无错误信息）'));
            nextCombo();
          });
      })();
    }
    // ---- 超长路分段锚点：全程 ≤4km/段等分切（高速除外——分段点全在主线中间必败，已走外扩） ----
    function trySegment(cb) {
      var nSeg = Math.min(6, Math.max(2, Math.ceil(distKm / 4)));
      var acc = [], segIdx = 0, anyFail = false;
      log('超长路分段 Driving：' + nSeg + ' 段（每段 ≤' + (distKm / nSeg).toFixed(1) + 'km）');
      (function nextSeg() {
        if (segIdx >= nSeg) {
          cb(dedupPts(acc));   // 全段成功=纯弯曲；部分失败段已用直线占位 → 混合
          return;
        }
        var pa = lerpPt(s, e, segIdx / nSeg);
        var pb = lerpPt(s, e, (segIdx + 1) / nSeg);
        var driving;
        try {
          driving = new AMap.Driving({ policy: AMap.DrivingPolicy.LEAST_TIME });
        } catch (err) {
          anyFail = true;
          acc.push(pa, pb);
          log('分段' + (segIdx + 1) + '/' + nSeg + ' Driving 初始化失败 → 该段直线占位');
          segIdx++;
          nextSeg();
          return;
        }
        driving.search(new AMap.LngLat(pa[0], pa[1]), new AMap.LngLat(pb[0], pb[1]),
          function (status, result) {
            var pts = (status === 'complete') ? extractRoute(result) : null;
            if (pts) {
              acc.push.apply(acc, pts);
              log('分段' + (segIdx + 1) + '/' + nSeg + ' OK 路径点=' + pts.length);
            } else {
              anyFail = true;
              acc.push(pa, pb);   // 该段直线占位
              log('分段' + (segIdx + 1) + '/' + nSeg + ' 失败 → 该段直线占位');
            }
            segIdx++;
            nextSeg();
          });
      })();
    }
    // ---- 全部引擎失败后的最终判定 ----
    function giveUp(reason) {
      if (distKm < 0.1) {
        log('直线距离不足 100m → 画施工圆点标记（零长度线不可见）');
        shortDotKeys[key] = true;   // 绘制端据此画圆点
        done(null);
      } else {
        log('全部引擎失败 → 直线兜底' + (reason ? '（' + reason + '）' : ''));
        done(null);
      }
    }

    // ---- 按序执行回退链 ----
    var chain = [];
    chain.push(function (cb) { amapSearch('Driving', 1, cb); });
    chain.push(function (cb) { amapSearch('Driving', -1, cb); });
    if (distKm <= 8) {
      chain.push(function (cb) { amapSearch('Walking', 1, cb); });
      chain.push(function (cb) { amapSearch('Walking', -1, cb); });
    }
    if (isHighway) chain.push(tryExtend);
    else if (distKm > 8) chain.push(trySegment);
    chain.push(function (cb) {
      log('高德引擎全败 → OSRM 开源路由兜底...');
      fetchOsrm(s, e, function (pts, err) {
        if (pts) {
          log('OSRM OK | 路径点=' + pts.length + '（WGS84→GCJ02 已纠偏）');
          cb(pts);
        } else {
          log('OSRM 失败 code=' + (err || '?') + (err === 'timeout' ? '（EU 服务器超时）' : ''));
          giveUp('OSRM ' + err);
        }
      });
    });
    (function runChain() {
      if (!chain.length) { giveUp(); return; }
      var step = chain.shift();
      step(function (pts) {
        if (pts) { routeCache[key] = pts; done(pts); return; }
        runChain();
      });
    })();
  }

  function clearRoadLines() {
    roadOverlays.forEach(function (o) { if (o && o.setMap) o.setMap(null); });
    roadOverlays = [];
    roadData = [];   // 清空点击判定数据（与图层同生命周期）
    dotMarkers = []; // 清空圆点标记
    lastActiveR = null;
    pendingRoad = null;
    pendingDistrict = '';
    clearHitSvg();   // 清空 SVG 点击热区
  }
  // 键匹配 roadData 条目（引用匹配 + 同区县同名兜底；防御列表/地图对象不一致）
  function findRoadEntry(r) {
    if (!r) return null;
    for (var i = 0; i < roadData.length; i++) {
      var rd = roadData[i];
      if (rd.r === r) return rd;
      if (rd.r && rd.r.district === r.district &&
        String(rd.r.road || rd.r.name) === String(r.road || r.name)) return rd;
    }
    return null;
  }
  // 道路当前显示路径点：entry.path（可能含真实弯曲）→ 回退 start/end 直线 → null（无坐标）
  function roadEntryPath(r) {
    if (!r) return null;
    var rd = findRoadEntry(r);
    if (rd && rd.path && rd.path.length >= 2) return rd.path;
    var s = r.start, e = r.end;
    if (!s || !e || s.length < 2 || e.length < 2) return null;
    return [s, e];
  }
  // 道路当前"视觉中心"：真实路径 bbox 中心 → 回退 start/end 中点（卡片锚点用；
  // 规划吸附可能偏离 Excel 原始点几百米，必须跟随真实路径否则卡片与线分离）
  // 关键：必须过滤范围外/异常点——若路径混入 (0,0) 之类，bbox 中心会算到海外，
  // InfoWindow autoMove 会把地图拉到非洲（"定位到非洲" bug 根因）
  function roadAnchor(r) {
    var pts = roadEntryPath(r);
    if (pts && pts.length) {
      var mn = [Infinity, Infinity], mx = [-Infinity, -Infinity];
      var has = false;
      for (var i = 0; i < pts.length; i++) {
        var lng = +pts[i][0], lat = +pts[i][1];
        if (!isFinite(lng) || !isFinite(lat)) continue;
        if (lng < 100 || lng > 130 || lat < 20 || lat > 45) continue;   // 只认中国东部范围
        if (lng < mn[0]) mn[0] = lng;
        if (lng > mx[0]) mx[0] = lng;
        if (lat < mn[1]) mn[1] = lat;
        if (lat > mx[1]) mx[1] = lat;
        has = true;
      }
      if (has) return [(mn[0] + mx[0]) / 2, (mn[1] + mx[1]) / 2];
    }
    var s = r && r.start, e = r && r.end;
    if (s && e && s.length >= 2 && e.length >= 2) return [(s[0] + e[0]) / 2, (s[1] + e[1]) / 2];
    return null;
  }

  function esc(s) {
    return String(s === undefined || s === null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  // ---------- 区县名归一化 ----------
  function normDistrict(d) {
    var mapN = {
      '海阳': '海阳市', '龙口': '龙口市', '莱阳': '莱阳市', '莱州': '莱州市',
      '招远': '招远市', '栖霞': '栖霞市', '蓬莱': '蓬莱区', '芝罘': '芝罘区',
      '福山': '福山区', '牟平': '牟平区', '莱山': '莱山区',
      '开发': '开发区', '高新': '高新区',
    };
    return mapN[d] || d;
  }

  // ---------- 左栏：施工道路列表（区县 tab + 全部道路 + 级别/状态筛选） ----------
  var workSide = { tab: 'all', district: '', level: 'all', status: 'all' };

  var workPeriod = '';   // 施工 2D 周期（本周/本月/今年）；'' = 跟随导航栏 getMqPeriod
  // 统一数据入口：ENGINEERING_DATA.roads 按当前周期（交底日期）过滤 —— 线绘制/左栏列表/
  // 中央窗口/区县计数全部同源，周期切换一处生效
  function getWorkRoads() {
    var eng = window.ENGINEERING_DATA || {};
    var roads = (eng.roads || []).slice();
    var period = workPeriod || (window.getMqPeriod ? window.getMqPeriod() : null) || '';
    if (period && window.filterWorkByPeriod) {
      roads = window.filterWorkByPeriod(roads, period);
    }
    return roads;
  }
  // 周期切换（导航栏 本周/本月/今年 → js.js 按钮调用）：2D 线/左栏列表/中央窗口按周期重建
  function refreshByPeriod(period) {
    workPeriod = period || '';
    if (!map) return;   // 2D 未创建：下次 show() 时 getWorkRoads 自动按导航栏周期生效
    addRoadLines();
    renderWorkLeftPanel();
    if (allRoadsWinOpen()) renderAllWinBody();
    console.log('[施工图] 周期切换 → ' + (period || '默认') + '：' + getWorkRoads().length + ' 条施工道路');
  }
  function wDistrictMatch(name, r) {
    if (!name) return false;
    var rd = normDistrict(r.district || '');
    if (rd === name) return true;
    if (name === '高新区' && rd === '烟台高新区') return true;
    if (name === '开发区' && rd === '烟台开发区') return true;
    return false;
  }
  function wLevelMatch(lv, r) {
    if (lv === 'all') return true;
    // level 字段兼容两种写法：字面色（红/橙/黄，Excel 转换脚本输出）与语义（干线/骨干汇聚/其他）
    var rl = String(r.level || '').trim();
    var isRed = rl.indexOf('干线') >= 0 || rl.indexOf('红') >= 0;
    var isOrange = rl.indexOf('骨干') >= 0 || rl.indexOf('汇聚') >= 0 || rl.indexOf('橙') >= 0;
    if (lv === 'red') return isRed;
    if (lv === 'orange') return isOrange;
    return !rl || (!isRed && !isOrange);
  }
  function wStatusMatch(st, r) {
    if (st === 'all') return true;
    return (r.status || '') === st;
  }
  // 根据一组道路定位视野：优先用真实路径点（roadData 里 entry.path，含弯曲折线），
  // 确保整条弯曲道路都在视野内；外扩留边再 setBounds 交给 AMap 自适应（不手动估 zoom）
  // 单路选中同样居中 —— 弹窗锚点=路径中心 → 卡片稳定落在屏幕中间
  function fitRoads(roads) {
    if (!map || !roads || !roads.length) return;
    var minLng = Infinity, maxLng = -Infinity, minLat = Infinity, maxLat = -Infinity;
    var has = false, firstName = '';
    roads.forEach(function (r) {
      if (!firstName) firstName = r.road || r.name || '';
      // 键匹配取当前显示路径（含真实弯曲；跨对象同名兜底）；无坐标路返回 null 跳过
      var pts = roadEntryPath(r);
      if (!pts) return;
      pts.forEach(function (p) {
        var lng = +p[0], lat = +p[1];
        if (!isFinite(lng) || !isFinite(lat)) return;
        if (lng < 100 || lng > 130 || lat < 20 || lat > 45) return;
        if (lng < minLng) minLng = lng;
        if (lng > maxLng) maxLng = lng;
        if (lat < minLat) minLat = lat;
        if (lat > maxLat) maxLat = lat;
        has = true;
      });
    });
    if (!has) return;
    // 异常跨度钳制：bbox 宽 >0.15°(~15km) 说明坐标/路线跨度异常（如标注 0.2km 但坐标跨 21km 的错误数据），
    // 若 setBounds 会把镜头拉到全景=用户观感"点击跳到错位置" → 改为居中 12 级
    var span = Math.max(maxLng - minLng, maxLat - minLat);
    if (span > 0.15) {
      console.log('[施工图] ' + (firstName || '?') + ' 坐标跨度异常 ' + (span * 101).toFixed(1) +
        'km → 居中定位(不拉全景)');
      var cLng = (minLng + maxLng) / 2, cLat = (minLat + maxLat) / 2;
      map.setZoomAndCenter(12, [cLng, cLat]);
      return;
    }
    var spanDeg = Math.max(maxLng - minLng, maxLat - minLat);
    // zoom 上限按跨度：短段(≤400m)可到 z21（0.2km 段 z20 视野 ~300m：整段+周边清晰）；长路保全景
    var capZoom = spanDeg < 0.004 ? 21 : (spanDeg < 0.012 ? 19 : 15);
    try {
      // 标准外扩 25% 对称居中框：道路/区县中心落在屏幕正中（视角不再南偏；
      // 详情卡片已改为容器内固定居中 DOM，不再依赖锚点 → 地图只需干净居中）
      var padLng = (maxLng - minLng) * 0.25 || 0.002;
      var padLat = (maxLat - minLat) * 0.25 || 0.001;
      var b = new AMap.Bounds(
        new AMap.LngLat(minLng - padLng, minLat - padLat),
        new AMap.LngLat(maxLng + padLng, maxLat + padLat)
      );
      // setBounds 让道路（含弯曲）完整入屏 + 留边；immediately=false → 播放下钻推近动画。
      map.setBounds(b, false, false, capZoom);
    } catch (err) {
      console.error('[施工图] fitRoads 定位失败:', err);
    }
  }
  // 等镜头动画真正结束（moveend）再弹卡 —— 固定延时会在动画未结束时开卡导致卡片偏位（"点两次才居中"根因）
  // force=true：无条件弹（首次选中）；force=false：卡片已被用户关闭则不打扰，仍开着则跟随新路径重开
  function openCardAfterMove(r, force) {
    if (!map || !r) return;
    fireWhenSettled(r, force, 1);
  }
  function fireWhenSettled(r, force, depth) {
    var fired = false;
    var fire = function () {
      if (fired) return;
      fired = true;
      if (map) map.off('moveend', fire);
      if (!force && roadCardOpen()) return;   // 用户已手动关闭卡片则不打扰
      // 名字/路径闭环校验：目标路的路径点必须真的在当前视野内（镜头与卡片对准同一条路）。
      // 点击瞬间规划未完成会用旧坐标 fit，规划完成重 fit 前若被其他操作打断 → 这里兜底重拉一次
      var pts = roadEntryPath(r);
      var inView = true;
      if (pts && pts.length) {
        inView = false;
        try {
          var b = map.getBounds();
          for (var i = 0; i < pts.length; i++) {
            if (b.contains(new AMap.LngLat(pts[i][0], pts[i][1]))) { inView = true; break; }
          }
        } catch (err) { inView = true; }
      }
      if (!inView && depth > 0) {
        console.log('[施工图] 镜头未对准 "' + (r.road || r.name || '') + '" → 按真实路径重新定位');
        fitRoads([r]);
        fireWhenSettled(r, force, depth - 1);   // fit 动画结束后再校验/弹卡
        return;
      }
      showRoadInfo(r);   // anchor 取当前最新路径中心 → 卡片居中
    };
    map.on('moveend', fire);
    setTimeout(fire, 1000);   // 兜底：目标与当前位置相同（无动画/moveend 不触发）也要开卡
  }
  // 道路所属区县中心（无坐标记录的模糊定位/弹窗位置）
  function districtCenterOf(r) {
    var name = r && (r.district || '');
    if (!name) return null;
    if (window.getDistrictCenter) {
      var c = window.getDistrictCenter(normDistrict(name));
      if (c && c.length === 2 && c[0] !== 120.78) return c;   // 120.78 = 全市兜底 → 视为无匹配
    }
    return null;
  }
  function fitRoad(r) { fitRoads([r]); }

  function renderWorkLeftPanel() {
    var li = document.querySelector('.mainbox .nav1 > li:first-child');
    if (!li) return;
    var panel = li.querySelector('.detail-panel');
    if (!panel) {
      panel = document.createElement('div');
      panel.className = 'detail-panel';
      li.appendChild(panel);
    }
    var all = getWorkRoads();
    // 列表 = 当前区县（workSide.district 非空时）再叠加级别/状态筛选
    var list = all.filter(function (r) {
      if (workSide.district && !wDistrictMatch(workSide.district, r)) return false;
      if (!wLevelMatch(workSide.level, r)) return false;
      if (!wStatusMatch(workSide.status, r)) return false;
      return true;
    });
    var dmap = {};
    all.forEach(function (r) {
      var k = normDistrict(r.district || '未分区');
      dmap[k] = (dmap[k] || 0) + 1;
    });
    var districts = Object.keys(dmap).sort(function (a, b) { return dmap[b] - dmap[a]; });
    var showDistrictRows = (workSide.tab === 'district' && !workSide.district);

    var html = '<div class="box"><div class="tit">施工道路</div><div class="boxnav">' +
      '<div class="dp-tabs">' +
      '<div class="dp-tab' + (workSide.tab === 'district' ? ' active' : '') + '" data-tab="district">区县</div>' +
      '<div class="dp-tab' + (workSide.tab === 'all' ? ' active' : '') + '" data-tab="all">全部道路</div>' +
      '</div>';

    if (showDistrictRows) {
      // 视图1：区县行列表（点击进入该区县道路子视图）
      districts.forEach(function (name) {
        html += '<div class="dp-item dp-district" data-district="' + esc(name) + '">' +
          '<span class="dp-dot yellow"></span>' +
          '<div class="dp-item-main">' +
          '<div class="dp-item-name">' + esc(name) + '</div>' +
          '<div class="dp-item-meta">' + dmap[name] + ' 条道路</div>' +
          '</div>' +
          '<span class="dp-rank">›</span></div>';
      });
      html += districts.length
        ? '<div class="dp-empty" style="padding-top:10px;">点击区县 → 查看该区县道路并定位</div>'
        : '<div class="dp-empty">该周期暂无施工道路（无交底记录）</div>';
    } else {
      // 视图2/3：区县道路子视图 or 全部道路（列表跟随 workSide.district 过滤）
      if (workSide.district) {
        html += '<div class="dp-item dp-back" data-back="1">' +
          '<span class="dp-rank">‹</span>' +
          '<div class="dp-item-main"><div class="dp-item-name" style="color:#7efbf6;">' +
          esc(workSide.district) + '（' + list.length + ' 条）</div>' +
          '<div class="dp-item-meta">返回区县列表</div></div></div>';
      }
      html += '<div class="dp-filters">' +
        '<div class="dp-filter' + (workSide.level === 'all' ? ' active' : '') + '" data-level="all">全部</div>' +
        '<div class="dp-filter f-red' + (workSide.level === 'red' ? ' active' : '') + '" data-level="red">干线</div>' +
        '<div class="dp-filter f-yellow' + (workSide.level === 'orange' ? ' active' : '') + '" data-level="orange">骨干</div>' +
        '<div class="dp-filter f-yellow' + (workSide.level === 'yellow' ? ' active' : '') + '" data-level="yellow">其他</div>' +
        '</div>';
      html += '<div class="dp-filters">' +
        '<div class="dp-filter' + (workSide.status === 'all' ? ' active' : '') + '" data-status="all">全部状态</div>' +
        '<div class="dp-filter' + (workSide.status === '施工中' ? ' active' : '') + '" data-status="施工中">施工中</div>' +
        '<div class="dp-filter' + (workSide.status === '已完工' ? ' active' : '') + '" data-status="已完工">已完工</div>' +
        '<div class="dp-filter' + (workSide.status === '未开工' ? ' active' : '') + '" data-status="未开工">未开工</div>' +
        '<div class="dp-filter' + (workSide.status === '暂停施工' ? ' active' : '') + '" data-status="暂停施工">暂停</div>' +
        '</div>';
      if (!list.length) {
        html += '<div class="dp-empty">该筛选下暂无道路</div>';
      } else {
        list.forEach(function (r, i) {
          var color = roadStatusColor(r.status);
          html += '<div class="dp-item" data-idx="' + i + '">' +
            '<span class="dp-dot" style="background:' + color + '"></span>' +
            '<div class="dp-item-main">' +
            '<div class="dp-item-name">' + esc(r.road || r.name || '') + '</div>' +
            '<div class="dp-item-meta">' + esc(normDistrict(r.district || '')) + ' · ' +
              (r.length_km ? r.length_km + 'km' : '') + ' · ' + esc(r.status || '') + '</div>' +
            '</div></div>';
        });
      }
    }
    html += '</div></div>';
    panel.innerHTML = html;
    // 绑定事件
    panel.querySelectorAll('.dp-tab').forEach(function (t) {
      t.onclick = function () {
        var tb = t.getAttribute('data-tab');
        if (!tb) return;
        if (tb === 'all') {
          // 全部道路 → 中央"全部道路"窗口（可搜索，样式复用预警图全部信息）+ 地图复原全区视角
          hideRoadCard();
          if (map) map.setZoomAndCenter(11, [120.78, 37.25]);
          showAllRoadsWindow();
          return;   // 窗口是浮层，左栏保持当前视图
        }
        // 区县 tab：关窗口 → 回到区县行列表
        hideAllRoadsWindow();
        workSide.tab = 'district';
        workSide.district = '';
        renderWorkLeftPanel();
      };
    });
    panel.querySelectorAll('.dp-district').forEach(function (it) {
      it.onclick = function () {
        var name = it.getAttribute('data-district');
        workSide.district = name;
        workSide.tab = 'district';   // 留在区县维度（子视图：该区县道路 + 返回行）
        workSide.level = 'all';      // 切换区县 = 全新视角：清掉残留级别/状态筛选
        workSide.status = 'all';
        renderWorkLeftPanel();
        console.log('[施工图] 区县定位: ' + name);
        if (!map) {
          pendingDistrict = name;    // 地图加载中：就绪后自动定位（列表已先可用）
          console.log('[施工图] 地图加载中，就绪后自动定位 ' + name);
          return;
        }
        fitDistrictRoads(name);
      };
    });
    panel.querySelectorAll('.dp-back').forEach(function (b) {
      b.onclick = function () {
        workSide.district = '';
        renderWorkLeftPanel();
      };
    });
    panel.querySelectorAll('.dp-filter').forEach(function (f) {
      f.onclick = function () {
        var lv = f.getAttribute('data-level');
        var st = f.getAttribute('data-status');
        if (lv) workSide.level = lv;
        if (st) workSide.status = st;
        renderWorkLeftPanel();
      };
    });
    panel.querySelectorAll('.dp-item[data-idx]').forEach(function (it) {
      it.onclick = function () {
        var r = list[parseInt(it.getAttribute('data-idx'), 10)];
        if (!r) return;
        selectRoad(r);   // 统一选中：定位+卡片（地图未就绪自动暂存，规划完成自动跟随）
      };
    });
  }

  // ============ "全部道路"中央窗口（复用 2D 预警图"全部信息"的 cl-* 观感；搜索+分组+点卡定位） ============
  var allWinMask = null, allWinPanel = null;
  var allWinQ = '', allWinTimer = null;
  function ensureAllWinDom(el) {
    if (allWinMask) return;
    allWinMask = document.createElement('div');
    allWinMask.className = 'work-all-mask';
    allWinMask.style.display = 'none';
    allWinMask.onclick = function () { hideAllRoadsWindow(); };
    allWinPanel = document.createElement('div');
    allWinPanel.className = 'work-all-panel';
    allWinPanel.style.display = 'none';
    // 头部只创建一次（搜索框不销毁 → 连续输入不卡、焦点不丢）
    var head = document.createElement('div');
    head.className = 'cl-head';
    head.innerHTML =
      '<span class="ai-title">全部施工道路<span class="ai-total"></span></span>' +
      '<input class="cl-search" type="text" placeholder="搜索道路 / 区县 / 状态">' +
      '<button class="ai-close" title="关闭">×</button>';
    allWinPanel.appendChild(head);
    var si = head.querySelector('.cl-search');
    var onQ = function () { allWinQ = si.value; scheduleAllWinFilter(); };
    si.addEventListener('input', onQ);
    si.addEventListener('keyup', onQ);
    head.querySelector('.ai-close').onclick = function () { hideAllRoadsWindow(); };
    // 阻止窗口内事件落到地图（点卡片不触发地图 click）
    allWinMask.addEventListener('mousedown', function (ev) { ev.stopPropagation(); });
    allWinPanel.addEventListener('mousedown', function (ev) { ev.stopPropagation(); });
    el.appendChild(allWinMask);
    el.appendChild(allWinPanel);
  }
  function showAllRoadsWindow() {
    var el = document.getElementById('workmap2d');
    if (!el) return;
    ensureAllWinDom(el);
    renderAllWinBody();
    allWinMask.style.display = 'block';
    allWinPanel.style.display = 'flex';
  }
  function hideAllRoadsWindow() {
    if (allWinMask) allWinMask.style.display = 'none';
    if (allWinPanel) allWinPanel.style.display = 'none';
  }
  function scheduleAllWinFilter() {
    if (allWinTimer) return;
    allWinTimer = setTimeout(function () { allWinTimer = null; applyAllWinFilter(); }, 150);
  }
  // 轻量过滤：只切换卡片/分组显隐，不重建 DOM（与 2D 预警图 applyFilter 同思路）
  function applyAllWinFilter() {
    if (!allWinPanel) return;
    var q = allWinQ.trim().toLowerCase();
    var visD = 0;
    allWinPanel.querySelectorAll('.cl-group').forEach(function (g) {
      var n = 0;
      g.querySelectorAll('.cl-item').forEach(function (c) {
        var hit = !q ||
          (c.getAttribute('data-name') || '').indexOf(q) >= 0 ||
          (c.getAttribute('data-district') || '').indexOf(q) >= 0 ||
          (c.getAttribute('data-status') || '').indexOf(q) >= 0;
        c.style.display = hit ? '' : 'none';
        if (hit) n++;
      });
      var showG = n > 0;
      g.style.display = showG ? '' : 'none';
      if (showG) visD++;
    });
    var total = allWinPanel.querySelector('.ai-total');
    if (total) total.textContent = '（' + visD + ' 个区县）';
  }
  function renderAllWinBody() {
    if (!allWinPanel) return;
    var roads = getWorkRoads();
    var groups = {};
    roads.forEach(function (r) {
      var d = normDistrict(r.district || '未分区');
      (groups[d] = groups[d] || []).push(r);
    });
    var keys = Object.keys(groups).sort(function (a, b) { return groups[b].length - groups[a].length; });
    var h = '<div class="cl-body">';
    keys.forEach(function (k) {
      h += '<div class="cl-group open" data-d="' + esc(k) + '">' +
        '<div class="cl-group-head" data-d="' + esc(k) + '">' +
        '<span class="cl-arrow">▾</span>' +
        '<span class="cl-district">' + esc(k) + '</span>' +
        '<span class="cl-total">共 ' + groups[k].length + ' 条</span>' +
        '</div><div class="ai-grid">';
      groups[k].forEach(function (r) {
        var color = roadStatusColor(r.status);
        var lv = { '红': '干线', '橙': '骨干汇聚', '黄': '其他' }[String(r.level || '').trim()] || r.level || '';
        h += '<div class="cl-item ai-card" data-name="' + esc(String(r.road || r.name || '').toLowerCase()) +
          '" data-district="' + esc(String(r.district || '').toLowerCase()) +
          '" data-status="' + esc(String(r.status || '').toLowerCase()) + '" data-idx="' +
          roads.indexOf(r) + '" title="' + esc(r.road || r.name || '') + '">' +
          '<div class="ai-top"><span class="cl-dot" style="background:' + color +
          ';box-shadow:0 0 6px ' + color + ';"></span>' +
          '<span class="ai-name">' + esc(r.road || r.name || '') + '</span></div>' +
          '<div class="ai-meta">' + esc(normDistrict(r.district || '')) + ' · ' + esc(lv) + ' · ' +
          esc(r.status || '') + '</div></div>';
      });
      h += '</div></div>';
    });
    h += '</div>';
    var old = allWinPanel.querySelector('.cl-body');
    if (old) old.remove();
    allWinPanel.insertAdjacentHTML('beforeend', h);
    // 点卡：关闭窗口 → 定位该路（fit + 固定详情卡）
    allWinPanel.querySelectorAll('.cl-item').forEach(function (c) {
      c.onclick = function () {
        var r = roads[parseInt(c.getAttribute('data-idx'), 10)];
        hideAllRoadsWindow();
        if (r) selectRoad(r);
      };
    });
    applyAllWinFilter();
  }

  // 道路详情卡（固定居中 DOM）状态修饰
  // 状态 → 修饰类（CSS st-green/st-gray/st-yellow/st-red）+ 徽章文字
  // （注：详情卡已从 AMap InfoWindow 改为容器内固定居中 DOM —— roadCardBox/ensureRoadCardBox）
  function roadStatusMod(r) {
    var s = String(r.status || '').trim();
    if (s.indexOf('施工中') >= 0) return { cls: 'st-green', txt: '施工中' };
    if (s.indexOf('已完工') >= 0) return { cls: 'st-gray', txt: '已完工' };
    if (s.indexOf('未开工') >= 0) return { cls: 'st-yellow', txt: '未开工' };
    if (s.indexOf('暂停') >= 0) return { cls: 'st-red', txt: '暂停施工' };
    return { cls: 'st-blue', txt: s || '施工道路' };
  }
  // ============ 道路详情卡（固定居中 DOM，不再用 InfoWindow 锚点 ============
  // 历史教训：InfoWindow 卡片永远钉在地理锚点上方 → 想让卡片居中就得偏置地图（视角南偏），
  // 想让地图居中卡片就偏上 → 两难。改为容器内固定居中卡片：地图干净居中(50%)，
  // 卡片固定屏幕正中 —— 两者互不干扰，任何道路点击都精确居中。
  var roadCardBox = null;
  function ensureRoadCardBox() {
    if (roadCardBox) return roadCardBox;
    var el = document.getElementById('workmap2d');
    if (!el) return null;
    roadCardBox = document.createElement('div');
    roadCardBox.className = 'work-card-float';
    roadCardBox.style.display = 'none';
    // 卡片上交互不落到地图（防点卡片触发地图 click 重选路/关卡）
    roadCardBox.addEventListener('mousedown', function (ev) { ev.stopPropagation(); });
    roadCardBox.addEventListener('click', function (ev) { ev.stopPropagation(); });
    el.appendChild(roadCardBox);
    return roadCardBox;
  }
  function hideRoadCard() {
    if (roadCardBox) roadCardBox.style.display = 'none';
  }
  function roadCardOpen() {
    return !!(roadCardBox && roadCardBox.style.display !== 'none');
  }
  function showRoadInfo(r) {
    if (!map || !r) return;
    var box = ensureRoadCardBox();
    if (!box) return;
    var s = r.start, e = r.end;
    var hasGeo = !!(s && e && s.length >= 2 && e.length >= 2);
    var lvlText = { '红': '干线', '橙': '骨干汇聚', '黄': '其他' }[String(r.level || '').trim()] || r.level || '';
    var mod = roadStatusMod(r);
    function frow(label, val) {
      return (val !== undefined && val !== null && String(val).trim() !== '')
        ? '<div class="wri-row"><span>' + esc(label) + '</span><b>' + esc(val) + '</b></div>' : '';
    }
    // 影响光缆条数 / 最高业务级别：两短字段合并一行展示
    var cableTxt = (r.cable_count !== undefined && r.cable_count !== null && r.cable_count !== '')
      ? r.cable_count + ' 条' : '';
    var fiberRow = frow('影响光缆', cableTxt) + frow('最高业务级别', r.biz_level || '');
    // 施工影响主要业务描述：长文本块（label 一行 + 正文多行可滚动）
    var descBlock = (r.biz_desc && String(r.biz_desc).trim())
      ? '<div class="wri-block"><span>施工影响主要业务</span>' +
        '<div class="wri-desc">' + esc(String(r.biz_desc)) + '</div></div>'
      : '';
    var info = document.createElement('div');
    info.className = 'work-road-card ' + mod.cls;   // 状态色修饰类：边框/徽章/名称线
    info.innerHTML =
      '<div class="wri-head">' +
        '<span class="wri-badge">' + esc(mod.txt) + '</span>' +
        '<button class="wri-close">×</button>' +
      '</div>' +
      '<div class="wri-name">' + esc(r.road || r.name || '') + '</div>' +
      frow('级别', lvlText || '—') +
      frow('状态', r.status || '—') +
      frow('区县', normDistrict(r.district || '—')) +
      frow('交底', (r.jiaodi_date ? (r.jiaodi || '') + ' · ' + r.jiaodi_date : '')) +
      fiberRow +
      descBlock +
      (r.coord_conflict
        ? '<div class="wri-nogeo">（⚠ 该记录坐标跨度与标注长度不符，已按施工点显示；请在 Excel 核对坐标后重跑转换）</div>'
        : (hasGeo ? '' : '<div class="wri-nogeo">（该记录无有效坐标，未在地图上画线）</div>'));
    box.innerHTML = '';
    box.appendChild(info);
    box.style.display = 'block';
    // 关闭按钮
    var closeBtn = info.querySelector('.wri-close');
    if (closeBtn) {
      closeBtn.onclick = function () { hideRoadCard(); };
    }
  }

  // ---------- 施工图入口：显示 #workmap2d + 左栏 + 画道路线 ----------
  // bbox = [minLng, minLat, maxLng, maxLat]（区县范围）：有则 setBounds 让区县占屏 ~80%；
  // 无 bbox（直接定位单点场景）回退 setZoomAndCenter
  // district = 标准区县名（可选）：从 3D 点区县进入 → 左栏默认显示该区县道路（非全区 65 条）
  // 注：地图道路线 = 一次全量加载所有区县（直线即时、弯曲队列渐进替换），不分区县
  function show(lng, lat, zoom, bbox, district) {
    // 通知 three-map 进入 2D：暂停 3D 渲染循环 + 隐藏 3D canvas + 加 detail-mode
    // （与 GaodeMap2D.show 对称；不调 onEnter 会导致 3D 持续渲染 → AMap 拖动卡顿）
    if (window.WorkMap2D.onEnter) window.WorkMap2D.onEnter();
    hideAllRoadsWindow();   // 重新进入不留上次的"全部道路"窗口
    // 左栏跟随进入区县：区县子视图 = 该区县道路列表（顶部"返回区县列表"可换区县）
    if (district) {
      workSide.tab = 'district';
      workSide.district = district;
      workSide.level = 'all';
      workSide.status = 'all';
    }
    // 渲染左栏施工道路列表（detail-mode 已由 three-map onEnter 添加，.box 隐藏、
    // .detail-panel 显示——与预警图 2D 完全同一套机制）
    renderWorkLeftPanel();
    var el = document.getElementById('workmap2d');
    if (!el) { console.error('[施工图] 无 #workmap2d 容器'); return; }
    el.style.display = 'block';
    // 首次加载 JS API（973KB）需要几秒：容器内放"加载中"提示，就绪后移除
    if (!window.AMap) {
      el.innerHTML = '<div class="workmap-loading">施工图地图加载中…</div>';
    }
    loadAmap().then(function () {
      // 隐藏 Leaflet 预警图 2D（互斥显示：同一时刻只有一个 2D）
      var map2d = document.getElementById('map2d');
      if (map2d && map2d.style.display !== 'none' && window.GaodeMap2D && window.GaodeMap2D.hide) {
        window.GaodeMap2D.hide();
      }
      if (!map) {
        // 首次创建：先清掉 loading 提示再建 AMap（此时容器内只有 loading div，安全）
        el.innerHTML = '';
        // features:['bg','road'] 已控制要素（道路含路名文字、无 point=无商店 POI）
        map = new AMap.Map(el, {
          zoom: 12,
          center: [lng, lat],
          viewMode: '2D',
          features: ['bg', 'road'],
        });
        setTimeout(function () { map.resize(); }, 120);
      } else {
        // 二次进入：map 已存在，DOM 不能动（el.innerHTML='' 会把地图 DOM 清空 → 白屏！）
        map.resize();
      }
      // 定位：优先按区县 bbox setBounds（贴合区县占屏 ~80%，留边不显全景）；
      // 无 bbox 时回退区县中心 + zoom
      if (bbox && bbox.length === 4 && bbox[0] < bbox[2] && bbox[1] < bbox[3]) {
        try {
          // 外扩 12% 留边 → 区县约占屏 88%？AMap setBounds 默认填满，
          // 外扩使区县占 ~80%（每侧留 10%）
          var padLng = (bbox[2] - bbox[0]) * 0.1;
          var padLat = (bbox[3] - bbox[1]) * 0.1;
          var b = new AMap.Bounds(
            new AMap.LngLat(bbox[0] - padLng, bbox[1] - padLat),
            new AMap.LngLat(bbox[2] + padLng, bbox[3] + padLat)
          );
          map.setBounds(b, false, false, 14);   // maxZoom 14：防超小区县被拉到 18（看不清周边）
        } catch (err) {
          console.error('[施工图] setBounds 失败，回退中心定位:', err);
          map.setZoomAndCenter(zoom || 11, [lng, lat]);
        }
      } else {
        map.setZoomAndCenter(zoom || 11, [lng, lat]);
      }
      addRoadLines();   // 全量画所有区县道路（直线即时 → 弯曲后台渐进替换）
      visible = true;
      // 补执行地图就绪前被暂存的选择（首次进入加载 JS API 需数秒，期间列表可点）
      if (pendingDistrict) {
        var pdName = pendingDistrict;
        pendingDistrict = '';
        console.log('[施工图] 地图就绪，补定位区县: ' + pdName);
        fitDistrictRoads(pdName);
      }
      if (pendingRoad) {
        var pr = pendingRoad;
        pendingRoad = null;
        lastActiveR = pr;
        setTimeout(function () {
          if (roadEntryPath(pr)) fitRoads([pr]);   // 缓存弯曲 → 直接定位真实线
          else {
            var pdc = districtCenterOf(pr);
            if (pdc) map.setZoomAndCenter(11, pdc);
          }
          openCardAfterMove(pr, true);
        }, 500);
      }
    }).catch(function (e) {
      console.error('[施工图] 高德 JS API 初始化失败:', e);
    });
  }

  function hide() {
    hideRoadCard();       // 关闭固定详情卡（防切换残留）
    hideAllRoadsWindow(); // 关闭"全部道路"中央窗口
    var el = document.getElementById('workmap2d');
    if (el) el.style.display = 'none';
    // 恢复 3D：显示 3D canvas + 恢复渲染循环 + 移除 detail-mode（左右栏回 3D 内容）
    if (window.WorkMap2D.onExit) window.WorkMap2D.onExit();
    visible = false;
  }

  function isVisible() {
    var el = document.getElementById('workmap2d');
    return !!(el && el.style.display !== 'none');
  }

  // 返回 3D 时由 three-map 调用（恢复 3D 渲染循环等，预留）
  function onExit() {
    hide();
    clearRoadLines();
  }

  // 底部模式按钮（柱状图/预警图/施工图）点击 → 切 3D 模式，收施工图 2D
  // （gaode-map-2d.js 的 onDomReady 只处理预警图自己的 hide，这里独立处理，
  //   保证两个 2D 模块互不依赖、互不干扰）
  function bindModeButtons() {
    document.querySelectorAll('.bottom-menu-item').forEach(function (btn) {
      btn.addEventListener('click', function () {
        hide();
        clearRoadLines();
      });
    });
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', bindModeButtons);
  } else {
    bindModeButtons();
  }

  window.WorkMap2D = {
    show: show,
    hide: hide,
    isVisible: isVisible,
    onExit: onExit,
    getMap: function () { return map; },
    refreshByPeriod: refreshByPeriod,   // 导航栏 本周/本月/今年 切换 → 2D 线/列表/窗口重建
    focusRoad: focusRoad,               // 底部施工日志点击 → 定位该施工道路
    showAllRoadsWindow: showAllRoadsWindow,   // "全部" → 中央全部道路窗口
  };
})();
