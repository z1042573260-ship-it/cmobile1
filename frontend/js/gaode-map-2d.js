// ============================================================
// 2D 在线高德街道地图（Leaflet + 高德瓦片，无需 key）
// 预警点标记 → 信息卡片 → "查看街道"（flyTo 定位到街道级）
// 暴露 window.GaodeMap2D：init / show(lng,lat,zoom) / hide / isVisible
// ============================================================
(function () {
  'use strict';

  var LEAFLET_CSS = [
    'https://cdn.jsdelivr.net/npm/leaflet@1.9.4/dist/leaflet.min.css',
    'https://cdn.bootcdn.net/ajax/libs/leaflet/1.9.4/leaflet.min.css',
  ];
  var LEAFLET_JS = [
    'https://cdn.jsdelivr.net/npm/leaflet@1.9.4/dist/leaflet.min.js',
    'https://cdn.bootcdn.net/ajax/libs/leaflet/1.9.4/leaflet.min.js',
  ];
  var TILE_URL = 'https://webrd0{s}.is.autonavi.com/appmaptile?lang=zh_cn&size=1&scale=1&style=8&x={x}&y={y}&z={z}';
  var SUBDOMAINS = '1234';

  var map = null;
  var loadingPromise = null;
  var markers = [];
  var infoCard = null;
  var initialized = false;

  // ---------- Leaflet 懒加载（jsdelivr → bootcdn 兜底） ----------
  function loadScript(url) {
    return new Promise(function (resolve, reject) {
      var s = document.createElement('script');
      s.src = url;
      s.onload = resolve;
      s.onerror = reject;
      document.head.appendChild(s);
    });
  }
  function loadLink(url) {
    return new Promise(function (resolve, reject) {
      var l = document.createElement('link');
      l.rel = 'stylesheet';
      l.href = url;
      l.onload = resolve;
      l.onerror = reject;
      document.head.appendChild(l);
    });
  }
  function tryLoad(urls, loader) {
    var i = 0;
    function attempt() {
      if (i >= urls.length) return Promise.reject(new Error('CDN 全部失败'));
      return loader(urls[i++]).catch(function () { return attempt(); });
    }
    return attempt();
  }
  function loadLeaflet() {
    return tryLoad(LEAFLET_CSS, loadLink)
      .then(function () { return tryLoad(LEAFLET_JS, loadScript); })
      .then(function () {
        if (!window.L) throw new Error('Leaflet 未就绪');
      });
  }

  function ensureMap() {
    if (map) return Promise.resolve();
    if (!loadingPromise) {
      loadingPromise = loadLeaflet().then(function () {
        var el = document.getElementById('map2d');
        if (!el) throw new Error('无 #map2d 容器');
        map = L.map(el, { zoomControl: false }).setView([37.25, 120.78], 10);
        L.control.zoom({ position: 'bottomright' }).addTo(map);
        L.tileLayer(TILE_URL, {
          subdomains: SUBDOMAINS,
          maxZoom: 18,
          attribution: '高德地图',
        }).addTo(map);
        // 点击地图空白处：关闭已打开的信息卡片（点击标记不会冒泡到这里）
        map.on('click', hideInfoCard);
        addMarkers();
      }).then(function () {
        loadingPromise = null;
        initialized = true;
      }).catch(function (e) {
        loadingPromise = null;
        console.error('[街道地图] 初始化失败:', e);
        throw e;
      });
    }
    return loadingPromise;
  }

  // ---------- 预警点标记 ----------
  // 周期过滤（与 3D 图钉同逻辑）：导航栏 本周/本月/今年 筛选为第一优先级，
  // 无日期的记录不属于任何周期 → 排除（与统计/柱状图一致）
  function inPeriod(p) {
    var start = (typeof periodStartStr === 'function') ? periodStartStr(_mqPeriod) : '';
    if (!start) return true;
    var d = String((p && p.publish_date) || '');
    if (!d) return false;
    return d >= start;
  }

  function addMarkers() {
    // 重建：先移除旧标记（数据更新后 2D 与 3D 保持一致，不再显示旧缓存数据）
    markers.forEach(function (m) { if (map) map.removeLayer(m); });
    markers = [];
    var data = window.DASHBOARD_DATA || {};
    var pts = (data.map_points || []).slice().filter(inPeriod);
    // 周期筛选（2026-08-20 用户要求）：2D 标记与 3D 图钉一致按 本周/本月/今年 过滤；
    // 同名/同坐标项目在详情卡片内翻页查看
    pts.forEach(function (p) {
      var v = p.value;
      if (!v || v.length < 2) return;
      var cls = p.category === 'red' ? 'red' : 'yellow';
      var icon = L.divIcon({
        className: 'g2d-marker-wrap',
        html: '<div class="g2d-marker ' + cls + '"></div>',
        iconSize: [16, 16],
        iconAnchor: [8, 8],
      });
      var m = L.marker([v[1], v[0]], {
        icon: icon,
        bubblingMouseEvents: false,   // 关键：marker 点击不冒泡到地图 click（否则详情刚弹出就被 map.on('click') 关掉）
      });
      m.bindTooltip(p.name, { direction: 'top', offset: [0, -8] });
      // 缩小/拖动后点击预警点：放大到对应街道级 + 底部详情页 + 刷新左右情报面板
      m.on('click', function () {
        var ll = m.getLatLng();
        if (map.getZoom() < 16) flyToPointUp(ll, 16);   // 点靠上，避开底部详情窗口
        showCenterDetail(p);   // 底部详情页（列表↔详情同区切换）
        renderDetailPanels(p);
      });
      m.addTo(map);
      markers.push(m);
    });
  }

  // ---------- 项目详情匹配（与 3D three-map 同逻辑：数据自身 MySQL 全字段 → workbuddy → project_list） ----------
  function matchDetail(p) {
    // 数据自带数据库全字段（导出自 export_dashboard_db.py）→ 直接用数据本身
    if (p && p.location !== undefined && p.ai_reason !== undefined) {
      return { src: 'db', row: p };
    }
    var nm = (p.name || '').trim();
    function matcher(name) {
      var full = (name || '').trim();
      if (!full || !nm) return false;
      return full === nm || (nm.length > 4 && full.indexOf(nm) === 0) || (full.length > 4 && nm.indexOf(full) === 0);
    }
    var wb = window.DASHBOARD_WORKBUDDY || [];
    for (var i = 0; i < wb.length; i++) {
      var it = wb[i] || {};
      if (it.district === p.district && matcher(it.project_name)) return { src: 'workbuddy', row: it };
    }
    var pl = (window.DASHBOARD_DATA && window.DASHBOARD_DATA.project_list) || [];
    for (var j = 0; j < pl.length; j++) {
      var it2 = pl[j] || {};
      if (it2.district === p.district && matcher(it2.name)) return { src: 'project_list', row: it2 };
    }
    return { src: 'none', row: null };
  }

  function esc(s) {
    return String(s === undefined || s === null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  // 近似同名判定（与 3D _nameSimilar 同规则）：前缀且长度差≥2 → 同一项目
  function nameSimilar(a, b) {
    if (!a || !b || a === b) return a === b;
    return (a.indexOf(b) === 0 && a.length > b.length + 1) || (b.indexOf(a) === 0 && b.length > a.length + 1);
  }
  // 同名记录数（近似同名组大小）：与 3D 折叠/2D 标记合并同规则
  function nameDupCount(p) {
    var nm = (p.name || '').trim();
    if (!nm) return 1;
    var pts = (window.DASHBOARD_DATA && window.DASHBOARD_DATA.map_points) || [];
    var n = 0;
    for (var i = 0; i < pts.length; i++) {
      if (pts[i] && nameSimilar(nm, (pts[i].name || '').trim())) n++;
    }
    return n;
  }

  // 全字段卡片 HTML（2D 地图"展现所有的"：workbuddy 29 字段 / project_list 摘要 / 基础兜底）
  function buildFullCardHtml(p, m) {
    var r = m.row || {};
    function row(label, val) {
      return (val !== undefined && val !== null && String(val).trim() !== '')
        ? '<div class="sic-row"><span>' + label + '</span><b>' + esc(val) + '</b></div>' : '';
    }
    // 规模：标签与值上下结构（放到下一行，值长不挤右端）
    function block(label, val) {
      return (val !== undefined && val !== null && String(val).trim() !== '')
        ? '<div class="sic-block"><span>' + label + '</span><div>' + esc(val) + '</div></div>' : '';
    }
    var html = '';
    if (m.src === 'db') {
      // 数据库全字段（导出自 export_dashboard_db.py）→ 直接用数据自身
      var dtel = r.telecom_needs;
      if (typeof dtel === 'string') {
        try { dtel = JSON.parse(dtel); } catch (e) { dtel = null; }
      }
      dtel = Array.isArray(dtel) ? dtel.join('、') : dtel;
      html += row('区县', r.district) + row('类型', r.project_type) + row('阶段', r.stage_detail || r.stage) +
        row('地点', r.location) + row('投资', r.investment) +
        block('规模', r.scale) +
        row('建设单位', r.developer) +
        row('发布日期', r.publish_date) +
        row('基站需求', r.need_base_station) + row('基站类型', r.base_station_type) +
        row('通信需求', dtel);
      if (r.ai_summary) html += '<div class="sic-summary"><span>原文摘要</span><div>' + esc(r.ai_summary) + '</div></div>';
      if (r.ai_reason) html += '<details open class="sic-details"><summary>AI 推理</summary><div>' + esc(r.ai_reason) + '</div></details>';
      if (r.content) html += '<details open class="sic-details"><summary>原文全文</summary><div>' + esc(r.content) + '</div></details>';
      if (r.source_url) html += '<a class="sic-link" href="' + esc(r.source_url) + '" target="_blank" rel="noopener">查看原文链接 ↗</a>';
    } else if (m.src === 'workbuddy') {
      var tel = Array.isArray(r.telecom_needs) ? r.telecom_needs.join('、') : r.telecom_needs;
      html += row('区县', r.district) + row('类型', r.project_type) + row('阶段', r.status) +
        row('地点', r.location) + row('投资', r.investment) +
        block('规模', r.scale) +
        row('建设单位', r.developer) +
        row('发布日期', r.publish_date) +
        row('基站需求', r.need_base_station) + row('基站类型', r.base_station_type) +
        row('通信需求', tel);
      if (r.ai_summary) html += '<div class="sic-summary"><span>原文摘要</span><div>' + esc(r.ai_summary) + '</div></div>';
      if (r.ai_reason) html += '<details open class="sic-details"><summary>AI 推理</summary><div>' + esc(r.ai_reason) + '</div></details>';
      if (r.content) html += '<details open class="sic-details"><summary>原文全文</summary><div>' + esc(r.content) + '</div></details>';
      if (r.source_url) html += '<a class="sic-link" href="' + esc(r.source_url) + '" target="_blank" rel="noopener">查看原文链接 ↗</a>';
    } else if (m.src === 'project_list') {
      html += row('区县', p.district) + row('类型', r.type || p.project_type) + row('阶段', r.stage || p.stage) +
        row('投资', r.investment) + block('规模', r.scale) + row('日期', r.date);
      if (r.ai_summary) html += '<div class="sic-summary"><span>原文摘要</span><div>' + esc(r.ai_summary) + '</div></div>';
      if (r.url) html += '<a class="sic-link" href="' + esc(r.url) + '" target="_blank" rel="noopener">查看原文链接 ↗</a>';
    } else {
      html += row('区县', p.district) + row('类型', p.project_type) + row('阶段', p.stage);
    }
    return html;
  }

  // 卡片定位：800×560 底部常驻（中下贴底，不跟随预警点；关闭卡片后露出中下列表）
  // 中间列可用宽 = 1920 - 左栏430 - 右栏430 = 1060；卡片 800 宽 → 两侧各余 130
  function positionCardRight(latLng) {
    if (!map || !infoCard) return;
    var el = document.getElementById('map2d');
    var rect = el.getBoundingClientRect();
    var cw = 800, ch = 560;
    var left = rect.left + (rect.width - cw) / 2;
    var top = rect.bottom - ch - 10;
    if (top < rect.top + 90) top = rect.top + 90;
    infoCard.style.left = left + 'px';
    infoCard.style.top = top + 'px';
    infoCard.style.right = 'auto';
  }

  // ---------- 信息卡片（2D 全字段，复用 .scatter-info-card 样式；定位标记右侧；已在街道级，无"详情"按钮） ----------
  // members/idx：同坐标组合并的翻页（与 3D 卡片一致）
  function showInfoCard(p, posLatLng, members, idx) {
    if (!infoCard) {
      infoCard = document.createElement('div');
      document.body.appendChild(infoCard);
    }
    var memList = (members && members.length > 1) ? members : null;
    var curIdx = (memList && idx !== undefined) ? idx : 0;
    var cls = p.category === 'red' ? 'red' : 'yellow';
    var m = matchDetail(p);
    // 同名记录标注（与 3D 卡片一致：数据库重复采集的近似同名记录数）
    var dupN = nameDupCount(p);
    var dupHtml = dupN > 1
      ? '<div class="sic-row"><span>同名记录</span><b>共 ' + dupN + ' 条</b></div>' : '';
    // 组内翻页导航
    var navHtml = memList
      ? '<div class="sic-nav">' +
        '<button class="sic-nav-btn" data-dir="-1">‹</button>' +
        '<span class="sic-page">' + (curIdx + 1) + '/' + memList.length + '</span>' +
        '<button class="sic-nav-btn" data-dir="1">›</button></div>' : '';
    infoCard.className = 'scatter-info-card ' + cls;
    infoCard.innerHTML =
      '<div class="sic-head"><span class="sic-tag ' + cls + '">' + (p.warning || '预警') + '</span>' +
      '<button class="sic-close">×</button></div>' +
      '<div class="sic-name">' + esc(p.name || '') + '</div>' +
      navHtml +
      dupHtml +
      buildFullCardHtml(p, m);
    infoCard.style.display = 'block';
    var closeBtn = infoCard.querySelector('.sic-close');
    if (closeBtn) closeBtn.onclick = hideInfoCard;
    // 组内翻页：‹/› 切换同坐标组的其他项目
    if (memList) {
      infoCard.querySelectorAll('.sic-nav-btn').forEach(function (btn) {
        btn.onclick = function () {
          var dir = parseInt(btn.getAttribute('data-dir'), 10);
          var ni = (curIdx + dir + memList.length) % memList.length;
          showInfoCard(memList[ni], posLatLng, memList, ni);
        };
      });
    }
    // 定位到标记右侧：先隐藏（避免"先卡在默认位置再跳"），定位完成再显示；
    // 等 flyTo 结束（moveend）再定位，动画中容器坐标会变；1.3s 兜底
    if (posLatLng) {
      infoCard.style.visibility = 'hidden';
      var positioned = false;
      var doPos = function () {
        if (positioned) return;
        positioned = true;
        positionCardRight(posLatLng);
        infoCard.style.visibility = 'visible';
      };
      if (map) {
        map.once('moveend', doPos);
        setTimeout(doPos, 1300);
      } else {
        doPos();
      }
    }
  }

  function hideInfoCard() {
    if (infoCard) infoCard.style.display = 'none';
  }

  // ---------- 详情页左右面板（项目情报工作台） ----------
  // 区县中心坐标共用 frontend/js/district-centers.js（window.getDistrictCenter）

  // 预警点列表（map_points 去重后；测试点除外——与 3D 图钉一致）
  function getWarningPoints() {
    var pts = (window.DASHBOARD_DATA && window.DASHBOARD_DATA.map_points) || [];
    var seen = {}, out = [];
    pts.forEach(function (p) {
      if (!inPeriod(p)) return;   // 周期筛选（与 3D 图钉一致）
      var v = p && p.value;
      if (!v || v.length < 2) return;
      var key = Math.round(v[0] * 1e4) + ',' + Math.round(v[1] * 1e4);
      if (seen[key]) return;
      seen[key] = true;
      out.push(p);
    });
    return out;
  }

  // 飞往指定坐标（zoom 等级），落地后让目标点偏上，避开底部详情窗口
  function flyToPointUp(latlng, zoom) {
    map.flyTo(latlng, zoom || 16, { duration: 1.0 });
    map.once('moveend', function () { map.panBy([0, 140]); });
  }
  // 点击预警列表项：飞向该点并弹出其详情（旧详情自动被覆盖切换）
  function flyToWarningPoint(p) {
    var v = p.value || [];
    if (!v.length) return;
    flyToPointUp([v[1], v[0]], 16);
    showCenterDetail(p);
  }

  // 左栏：预警列表（区县/当前区/全部区 tab + 红黄筛选）
  // 13 个正式区县（含功能区）；区县 tab 点击 → 定位区县中心看全貌 + 切到该区预警
  var DISTRICT_LIST = ['芝罘区', '福山区', '牟平区', '莱山区', '蓬莱区', '龙口市', '莱阳市', '莱州市', '招远市', '栖霞市', '海阳市', '高新区', '开发区'];
  function districtMatch(name, p) {
    if (!name) return false;
    // 统计口径（与 js.js statDistrict 一致）：开发区（功能区）项目计入福山区
    if (typeof statDistrict === 'function' && statDistrict(p.district) === name) return true;
    if (p.district === name) return true;
    if (name === '高新区' && p.district === '烟台高新区') return true;
    if (name === '开发区' && p.district === '烟台开发区') return true;
    return false;
  }
  var sideState = { tab: 'all', filter: 'all', district: '' };
  function renderLeftPanel(pt) {
    var li = document.querySelector('.mainbox .nav1 > li:first-child');
    if (!li) return;
    var panel = li.querySelector('.detail-panel');
    if (!panel) {
      panel = document.createElement('div');
      panel.className = 'detail-panel';
      li.appendChild(panel);
    }
    var district = sideState.district || pt.district || '';
    var all = getWarningPoints();
    var list;
    if (sideState.tab === 'district') {
      list = [];
    } else if (sideState.tab === 'current') {
      list = all.filter(function (p) { return districtMatch(district, p); });
    } else {
      list = all.slice();
    }
    if (sideState.filter === 'red') list = list.filter(function (p) { return p.category === 'red'; });
    if (sideState.filter === 'yellow') list = list.filter(function (p) { return p.category === 'yellow'; });
    var html = '<div class="box"><div class="tit">预警列表</div><div class="boxnav">' +
      '<div class="dp-tabs">' +
      '<div class="dp-tab' + (sideState.tab === 'district' || sideState.tab === 'current' ? ' active' : '') + '" data-tab="district">区县</div>' +
      '<div class="dp-tab dp-cur' + (sideState.tab === 'current' ? ' active' : '') + '">当前区：' + esc(district || '—') + '</div>' +
      '<div class="dp-tab' + (sideState.tab === 'all' ? ' active' : '') + '" data-tab="all">全部信息</div>' +
      '</div>';
    if (sideState.tab === 'district') {
      // 区县列表：每个区县 + 红/黄预警数；点击 → 定位区县中心（缩小看全貌）+ 切当前区
      DISTRICT_LIST.forEach(function (name) {
        var reds = all.filter(function (p) { return districtMatch(name, p) && p.category === 'red'; }).length;
        var yellows = all.filter(function (p) { return districtMatch(name, p) && p.category === 'yellow'; }).length;
        html += '<div class="dp-item dp-district" data-district="' + name + '">' +
          '<span class="dp-dot ' + (reds ? 'red' : 'yellow') + '"></span>' +
          '<div class="dp-item-main">' +
          '<div class="dp-item-name">' + name + '</div>' +
          '<div class="dp-item-meta">红色 ' + reds + ' · 黄色 ' + yellows + '</div>' +
          '</div>' +
          '<span class="dp-rank">›</span></div>';
      });
      html += '<div class="dp-empty" style="padding-top:10px;">点击区县 → 地图缩小看全区概况，再点预警点下钻</div>';
    } else if (sideState.tab === 'all') {
      // 全部信息：中下弹出大窗口，所有项目按区县分类展示
      html += '<div class="dp-empty" style="padding-top:10px;">已弹出「全部信息」窗口：全部项目按区县分类展示</div>';
    } else {
      html += '<div class="dp-filters">' +
        '<div class="dp-filter' + (sideState.filter === 'all' ? ' active' : '') + '" data-filter="all">全部</div>' +
        '<div class="dp-filter f-red' + (sideState.filter === 'red' ? ' active' : '') + '" data-filter="red">红色预警</div>' +
        '<div class="dp-filter f-yellow' + (sideState.filter === 'yellow' ? ' active' : '') + '" data-filter="yellow">黄色预警</div>' +
        '</div>';
      if (!list.length) {
        html += '<div class="dp-empty">该筛选下暂无预警点</div>';
      } else {
        list.forEach(function (p) {
          var cls = p.category === 'red' ? 'red' : 'yellow';
          html += '<div class="dp-item" data-idx="' + list.indexOf(p) + '">' +
            '<span class="dp-dot ' + cls + '"></span>' +
            '<div class="dp-item-main">' +
            '<div class="dp-item-name">' + esc(p.name || '') + '</div>' +
            '<div class="dp-item-meta">' + esc(p.district || '') + ' · ' + esc(p.project_type || '') + ' · ' + esc(p.stage || '') + '</div>' +
            '</div></div>';
        });
      }
    }
    html += '</div></div>';
    panel.innerHTML = html;
    panel.querySelectorAll('.dp-tab').forEach(function (t) {
      t.onclick = function () {
        var tb = t.getAttribute('data-tab');
        if (!tb) return;   // 只读 tab（当前区县）无行为
        sideState.tab = tb;
        if (sideState.tab === 'all') showAllInfo();   // 全部信息 → 中下弹出大窗口（按区县分类）
        else if (centerState.allinfo) hideAllInfo();  // 切走全部信息 → 关闭大窗口
        if (sideState.tab !== 'district') sideState.district = '';   // 手动切 tab 时回到默认当前区
        renderLeftPanel(pt);
      };
    });
    panel.querySelectorAll('.dp-filter').forEach(function (f) {
      f.onclick = function () { sideState.filter = f.getAttribute('data-filter'); renderLeftPanel(pt); };
    });
    panel.querySelectorAll('.dp-district').forEach(function (it) {
      it.onclick = function () {
        var name = it.getAttribute('data-district');
        sideState.district = name;
        sideState.tab = 'current';
        hideCenterDetail();   // 看区县全貌 → 详情卡消失，不挡地图
        var c = window.getDistrictCenter(name);
        map.flyTo([c[1], c[0]], 11, { duration: 1.0 });   // 缩小看全区概况
        renderLeftPanel(pt);
      };
    });
    panel.querySelectorAll('.dp-item[data-idx]').forEach(function (it) {
      it.onclick = function () { flyToWarningPoint(list[parseInt(it.getAttribute('data-idx'), 10)]); };
    });
  }

  // 右栏：同类项目对比（数据库 project_list 同 type Top 10，按 priority 降序；随选中项目变化）
  function renderRightPanel(pt, m) {
    var li = document.querySelector('.mainbox .nav1 > li:last-child');
    if (!li) return;
    var panel = li.querySelector('.detail-panel');
    if (!panel) {
      panel = document.createElement('div');
      panel.className = 'detail-panel';
      li.appendChild(panel);
    }
    var row = m.row || {};
    var type = (row.project_type || row.type || pt.project_type || '').trim();
    var curName = (row.project_name || row.name || pt.name || '').trim();
    var pl = (window.DASHBOARD_DATA && window.DASHBOARD_DATA.project_list) || [];
    var same = pl.filter(function (it) {
      return it && it.type === type && (it.name || '').trim() !== curName;
    }).sort(function (a, b) { return (b.priority || 0) - (a.priority || 0); }).slice(0, 10);
    var html = '<div class="box"><div class="tit">同类项目对比' + (type ? '（' + esc(type) + '）' : '') + '</div><div class="boxnav">';
    if (!same.length) {
      html += '<div class="dp-empty">暂无同类项目</div>';
    } else {
      same.forEach(function (it, i) {
        html += '<div class="dp-item" data-idx="' + i + '">' +
          '<span class="dp-rank">' + (i + 1) + '</span>' +
          '<div class="dp-item-main">' +
          '<div class="dp-item-name">' + esc(it.name || '') + '</div>' +
          '<div class="dp-item-meta">' + esc(it.district || '') + ' · 投资 ' + esc(it.investment || '—') + ' · 优先级 ' + (it.priority || '—') + '</div>' +
          '</div></div>';
      });
    }
    html += '</div></div>';
    panel.innerHTML = html;
    panel.querySelectorAll('.dp-item').forEach(function (it) {
      it.onclick = function () {
        var item = same[parseInt(it.getAttribute('data-idx'), 10)];
        if (!item || !map) return;
        // 优先精确坐标（map_points 匹配），否则定位到区县中心
        var pts = getWarningPoints();
        var hit = null;
        var nm = (item.name || '').trim();
        for (var k = 0; k < pts.length; k++) {
          var pn = (pts[k].name || '').trim();
          if (pts[k].district === item.district && pn &&
            (pn === nm || (nm.length > 4 && pn.indexOf(nm) === 0) || (nm.length > 4 && nm.indexOf(pn) === 0))) { hit = pts[k]; break; }
        }
        if (hit) {
          flyToWarningPoint(hit);
        } else {
          var c = window.getDistrictCenter(item.district);
          map.flyTo([c[1], c[0]], 11, { duration: 1.0 });
        }
      };
    });
  }

  function renderDetailPanels(pt) {
    var m = matchDetail(pt);   // 内部匹配，避免调用点漏传 m 导致右栏崩溃
    renderLeftPanel(pt);
    renderRightPanel(pt, m);
  }

  // 右栏：全部模式对比（数据库 project_list 按 priority 降序 Top10，点击定位）
  function renderRightPanelAll() {
    var li = document.querySelector('.mainbox .nav1 > li:last-child');
    if (!li) return;
    var panel = li.querySelector('.detail-panel');
    if (!panel) {
      panel = document.createElement('div');
      panel.className = 'detail-panel';
      li.appendChild(panel);
    }
    var pl = (window.DASHBOARD_DATA && window.DASHBOARD_DATA.project_list) || [];
    var items = pl.slice().sort(function (a, b) { return (b.priority || 0) - (a.priority || 0); }).slice(0, 10);
    var html = '<div class="box"><div class="tit">同类项目对比（全部）</div><div class="boxnav">';
    if (!items.length) {
      html += '<div class="dp-empty">暂无同类项目</div>';
    } else {
      items.forEach(function (it, i) {
        html += '<div class="dp-item" data-idx="' + i + '">' +
          '<span class="dp-rank">' + (i + 1) + '</span>' +
          '<div class="dp-item-main">' +
          '<div class="dp-item-name">' + esc(it.name || '') + '</div>' +
          '<div class="dp-item-meta">' + esc(it.district || '') + ' · 投资 ' + esc(it.investment || '—') + ' · 优先级 ' + (it.priority || '—') + '</div>' +
          '</div></div>';
      });
    }
    html += '</div></div>';
    panel.innerHTML = html;
    panel.querySelectorAll('.dp-item').forEach(function (it) {
      it.onclick = function () {
        var item = items[parseInt(it.getAttribute('data-idx'), 10)];
        if (!item || !map) return;
        // 优先精确坐标（map_points 匹配），否则定位到区县中心
        var pts = getWarningPoints();
        var hit = null;
        var nm = (item.name || '').trim();
        for (var k = 0; k < pts.length; k++) {
          var pn = (pts[k].name || '').trim();
          if (pts[k].district === item.district && pn &&
            (pn === nm || (nm.length > 4 && pn.indexOf(nm) === 0) || (nm.length > 4 && nm.indexOf(pn) === 0))) { hit = pts[k]; break; }
        }
        if (hit) {
          flyToWarningPoint(hit);
        } else {
          var c = window.getDistrictCenter(item.district);
          map.flyTo([c[1], c[0]], 11, { duration: 1.0 });
        }
      };
    });
  }

  // 全部视图：2D 全市 + 左栏预警列表(全部信息 tab) + 右栏同类项目对比 + 中央全部信息窗口
  function openAllView() {
    ensureMap().then(function () {
      show();   // 2D 全市视图（不定位单点）
      sideState.tab = 'all';
      sideState.district = '';
      var pts = getWarningPoints();
      var pt = pts[0] || {};
      showAllInfo();        // 中央全部信息窗口
      renderLeftPanel(pt);  // 左栏预警列表（全部信息 tab active）
      renderRightPanelAll();// 右栏同类项目对比（全部）
    }).catch(function () {
      console.error('[全部视图] 打开失败');
    });
  }

  // ---------- 中央/底部面板：详情=底部上滑，全部信息=中央弹窗+遮罩 ----------
  // 数据 = dashboard_data 原始 map_points(13) + workbuddy 覆盖后(10) 合并去重，模拟"全部"
  var centerState = { filter: 'all', open: {}, detail: null, allinfo: false, mapClickBound: false, selected: -1, cardDetail: null, prevDetail: null, q: '', composing: false };
  function getCenterPoints() {
    var d = window.DASHBOARD_DATA || {};
    var arr = (d.map_points_original || []).concat(d.map_points || []);
    var seen = {}, out = [];
    arr.forEach(function (p) {
      if (!p || !p.value || p.value.length < 2) return;
      if (!inPeriod(p)) return;   // 与地图标记/左栏列表同口径（周期筛选，防止窗口显示全量但地图无标记）
      var key = Math.round(p.value[0] * 1e4) + ',' + Math.round(p.value[1] * 1e4);
      if (seen[key]) return;
      seen[key] = true;
      out.push(p);
    });
    return out;
  }
  // 创建面板 + 公共事件委托（只创建/绑定一次）
  function ensurePanel() {
    var el = document.getElementById('map2d');
    if (!el) return null;
    var panel = document.getElementById('center-list');
    if (panel) return panel;
    panel = document.createElement('div');
    panel.id = 'center-list';
    el.appendChild(panel);
    // 阻止滚轮冒泡到 Leaflet 地图（否则滚轮直接缩放地图、面板无法滚动）
    panel.addEventListener('wheel', function (e) { e.stopPropagation(); }, { passive: true });
    // 搜索输入（全部信息窗口）：委托层兜底过滤 + 阻止冒泡防误关
    // 注意：组合输入（拼音）过程中跳过 + 防抖合并，避免每次按键都 applyFilter 导致卡顿
    panel.addEventListener('input', function (e) {
      e.stopPropagation();   // 防止冒泡到 Leaflet 地图（其 click 会误关窗口）
      if (centerState.composing) return;
      if (e.target.classList && e.target.classList.contains('cl-search')) {
        centerState.q = e.target.value;
        scheduleFilter();
      }
    });
    // 事件委托：筛选、分组折叠、点条目 → 中央详情；跳转地图；× → 关闭
    panel.addEventListener('click', function (e) {
      e.stopPropagation();   // 关键：阻止冒泡到 Leaflet 地图（否则任何面板点击都被当"地图空白"关闭窗口）
      var cback = e.target.closest ? e.target.closest('.cd-back') : null;
      if (cback) { showAllInfo(); return; }   // 中央详情 → 返回全部信息列表
      var cj = e.target.closest ? e.target.closest('.cd-jump') : null;
      if (cj) {
        // 中央详情里的「跳转地图」→ 关弹窗 + 飞到该项目 + 底部弹出详情
        var jp = centerState.cardDetail;
        if (jp) {
          hideAllInfo();
          var v = jp.value || [];
          if (v.length) flyToPointUp([v[1], v[0]], 16);
          showCenterDetail(jp);
          renderDetailPanels(jp);
        }
        return;
      }
      var f = e.target.closest ? e.target.closest('.cl-filter') : null;
      if (f) { centerState.filter = f.getAttribute('data-f'); applyFilter(); return; }
      var gh = e.target.closest ? e.target.closest('.cl-group-head') : null;
      if (gh) {
        // 折叠：只切 class/箭头，不重建
        var d = gh.getAttribute('data-d');
        centerState.open[d] = centerState.open[d] !== false ? false : true;
        var g = gh.closest('.cl-group');
        var grid = g && g.querySelector('.ai-grid');
        if (grid) grid.style.display = centerState.open[d] ? '' : 'none';
        var ar = gh.querySelector('.cl-arrow');
        if (ar) ar.textContent = centerState.open[d] ? '▾' : '▸';
        return;
      }
      // 卡片「跳转地图」按钮 → 关弹窗 + 飞到该项目 + 底部弹出详情
      var jump = e.target.closest ? e.target.closest('.ai-jump') : null;
      if (jump) {
        var ji = parseInt(jump.getAttribute('data-i'), 10);
        var jp2 = centerState.list && centerState.list[ji];
        if (jp2) {
          hideAllInfo();
          var v2 = jp2.value || [];
          if (v2.length) flyToPointUp([v2[1], v2[0]], 16);
          showCenterDetail(jp2);
          renderDetailPanels(jp2);
        }
        return;
      }
      var item = e.target.closest ? e.target.closest('.cl-item') : null;
      if (item) {
        // 点卡片 → 窗口原地变成该项目的详细信息（不跳转地图）
        var idx = parseInt(item.getAttribute('data-i'), 10);
        var p = centerState.list && centerState.list[idx];
        if (p) showCardDetail(p);
        return;
      }
      var close = e.target.closest ? (e.target.closest('.cd-close') || e.target.closest('.ai-close')) : null;
      if (close) {
        if (centerState.allinfo) hideAllInfo();
        else if (centerState.detail) hideCenterDetail();
      }
    });
    return panel;
  }
  // 全部信息遮罩：挂到 #map2d 内，只遮地图（左右栏 z-index 999 > map2d 保持高亮；
  // 面板 z-index 800 在同一层叠上下文内，位于遮罩 799 之上，窗口不会被压暗）
  function ensureMask() {
    var el = document.getElementById('map2d');
    if (!el) return null;
    var mask = document.getElementById('center-mask');
    if (!mask) {
      mask = document.createElement('div');
      mask.id = 'center-mask';
      el.appendChild(mask);
      mask.addEventListener('click', function () { hideAllInfo(); });
    }
    return mask;
  }

  // ---------- 底部详情页（方案 B：与中下列表同区切换，1028 宽 × ~460 高，字段双列网格） ----------
  // navHtml（可选）：翻页导航插入"名称"与"内容"之间（与 3D 卡片同一位置：名称下、字段上）
  function buildDetailHtml(p, m, navHtml) {
    var r = m.row || {};
    var cls = p.category === 'red' ? 'red' : 'yellow';
    var warn = p.warning || (cls === 'red' ? '红色预警' : '黄色预警');
    function field(label, val) {
      return (val !== undefined && val !== null && String(val).trim() !== '')
        ? '<div class="cd-field"><span>' + label + '</span><b>' + esc(val) + '</b></div>' : '';
    }
    var left = '<div class="cd-grid">';
    if (m.src === 'db') {
      // 数据库全字段（导出自 export_dashboard_db.py）→ 直接用数据自身
      var dtel2 = r.telecom_needs;
      if (typeof dtel2 === 'string') {
        try { dtel2 = JSON.parse(dtel2); } catch (e) { dtel2 = null; }
      }
      dtel2 = Array.isArray(dtel2) ? dtel2 : (dtel2 ? [dtel2] : []);
      left += field('类型', r.project_type) + field('阶段', r.stage_detail || r.stage) +
        field('地点', r.location) + field('投资', r.investment) + field('规模', r.scale) +
        field('建设单位', r.developer) +
        field('发布日期', r.publish_date) +
        field('基站需求', r.need_base_station) + field('基站类型', r.base_station_type);
      if (r.ai_summary) left += '<div class="cd-summary"><span>原文摘要</span><div>' + esc(r.ai_summary) + '</div></div>';
    } else if (m.src === 'workbuddy') {
      var tel = Array.isArray(r.telecom_needs) ? r.telecom_needs : (r.telecom_needs ? [r.telecom_needs] : []);
      left += field('类型', r.project_type) + field('阶段', r.status) +
        field('地点', r.location) + field('投资', r.investment) + field('规模', r.scale) +
        field('建设单位', r.developer) +
        field('发布日期', r.publish_date) +
        field('坐标', (r.lng !== undefined && r.lat !== undefined) ? (r.lng + ', ' + r.lat) : '') +
        field('坐标来源', r.geo_source) +
        field('基站需求', r.need_base_station) + field('基站类型', r.base_station_type);
      if (r.ai_summary) left += '<div class="cd-summary"><span>原文摘要</span><div>' + esc(r.ai_summary) + '</div></div>';
    } else if (m.src === 'project_list') {
      left += field('类型', r.type || p.project_type) + field('阶段', r.stage || p.stage) +
        field('投资', r.investment) + field('规模', r.scale) + field('日期', r.date);
      if (r.ai_summary) left += '<div class="cd-summary"><span>原文摘要</span><div>' + esc(r.ai_summary) + '</div></div>';
    } else {
      left += field('类型', p.project_type) + field('阶段', p.stage);
    }
    left += '</div>';
    // 右区：通信需求标签 + AI 推理 + 原文全文（直接展示，不折叠；db/workbuddy 均支持）
    var right = '<div class="cd-sec-title">通信需求</div>';
    var needs = (m.src === 'db' || m.src === 'workbuddy') && Array.isArray(r.telecom_needs) ? r.telecom_needs : [];
    if (needs.length) {
      right += '<div class="cd-tags">';
      needs.forEach(function (t) { right += '<span>' + esc(t) + '</span>'; });
      right += '</div>';
    } else {
      right += '<div class="cd-none">暂无通信需求标注</div>';
    }
    if ((m.src === 'db' || m.src === 'workbuddy') && r.ai_reason) {
      right += '<div class="cd-sec-title" style="margin-top:14px;">AI 推理</div>' +
        '<div class="cd-text">' + esc(r.ai_reason) + '</div>';
    }
    if ((m.src === 'db' || m.src === 'workbuddy') && r.content) {
      right += '<div class="cd-sec-title" style="margin-top:14px;">原文全文</div>' +
        '<div class="cd-text">' + esc(r.content) + '</div>';
    }
    var link = m.src === 'db' ? r.source_url : (m.src === 'workbuddy' ? r.source_url : (m.src === 'project_list' ? r.url : ''));
    if (link) right += '<a class="cd-link" href="' + esc(link) + '" target="_blank" rel="noopener">查看原文链接 ↗</a>';
    // 项目名用完整名（数据库/AI 库完整 project name；map_points 的 name 可能截断）
    var fullName = r.project_name || r.name || p.name || '';
    return '<div class="cd-head">' +
      '<span class="cd-badge ' + cls + '">' + esc(warn) + '</span>' +
      '<div class="cd-name">' + esc(fullName) + '</div>' +
      '<button class="cd-close" title="关闭详情（回到列表）">×</button>' +
      '</div>' +
      '<div class="cd-body">' +
      '<div class="cd-left">' + left + '</div>' +
      '<div class="cd-right">' + right + '</div>' +
      '</div>' +
      (navHtml || '') +   // 翻页导航：面板底部（2D 详情与 3D 卡片位置不同，用户要求放下方）
      '';
  }
  function showCenterDetail(p, members, idx) {
    var panel = ensurePanel();
    if (!panel) return;
    if (centerState.allinfo) hideAllInfo();   // 全部信息开着 → 先关（弹窗与详情不同时出现）
    // 同坐标组翻页（与 3D 卡片一致：同坐标组合并，可翻看组内所有项目）
    var memList = (members && members.length > 1) ? members : null;
    if (!memList && p.value && p.value.length >= 2) {
      var ck = Math.round(p.value[0] * 1e4) + ',' + Math.round(p.value[1] * 1e4);
      var all = (window.DASHBOARD_DATA && window.DASHBOARD_DATA.map_points) || [];
      memList = all.filter(function (q) {
        return q && q.value && q.value.length >= 2 &&
          Math.round(q.value[0] * 1e4) + ',' + Math.round(q.value[1] * 1e4) === ck;
      });
      if (memList.length <= 1) memList = null;
    }
    var curIdx = 0;
    if (memList) {
      curIdx = memList.indexOf(p);
      if (curIdx < 0) curIdx = 0;
    }
    var m = matchDetail(p);
    centerState.detail = p;
    panel.classList.remove('allinfo');
    panel.classList.add('detail');
    panel.style.display = 'flex';
    var navHtml = memList
      ? '<div class="sic-nav">' +
        '<button class="sic-nav-btn" data-dir="-1">‹</button>' +
        '<span class="sic-page">' + (curIdx + 1) + '/' + memList.length + '</span>' +
        '<button class="sic-nav-btn" data-dir="1">›</button></div>' : '';
    panel.innerHTML = buildDetailHtml(p, m, navHtml);   // 详情 = 徽章+名称 + 翻页导航（名称下，与 3D 卡片一致）+ 内容
    if (memList) {
      panel.querySelectorAll('.sic-nav-btn').forEach(function (btn) {
        btn.onclick = function () {
          var dir = parseInt(btn.getAttribute('data-dir'), 10);
          var ni = (curIdx + dir + memList.length) % memList.length;
          showCenterDetail(memList[ni], memList, ni);
        };
      });
    }
    // 底部上滑动画
    panel.style.bottom = '-540px';
    requestAnimationFrame(function () {
      panel.style.bottom = '10px';
    });
    ensureMapClickClose();
  }
  // 地图空白点击 → 关闭详情/全部信息（marker 点击不冒泡，安全）
  function ensureMapClickClose() {
    if (map && !centerState.mapClickBound) {
      centerState.mapClickBound = true;
      map.on('click', function () {
        if (centerState.allinfo) hideAllInfo();
        else if (centerState.detail) hideCenterDetail();
      });
    }
  }
  function hideCenterDetail() {
    centerState.detail = null;
    var panel = document.getElementById('center-list');
    if (panel) {
      panel.classList.remove('detail');
      panel.style.display = 'none';
      panel.innerHTML = '';   // 清空残留（否则下次打开全部信息时旧详情会留在窗口顶部）
    }
  }

  // ---------- 全部信息：屏幕中央弹窗（所有项目按区县分类，遮罩+×关闭） ----------
  // 全量渲染一次，之后搜索/筛选只切换显隐（零 DOM 重建，数据再多也不卡）
  function showAllInfo() {
    var panel = ensurePanel();
    if (!panel) return;
    ensureMapClickClose();
    // 记录打开前是否有具体预警点详情：关闭全部信息后恢复它（用户点预警点 → 全部信息 → 关闭，详情窗口不应消失）
    if (centerState.detail) centerState.prevDetail = centerState.detail;
    if (centerState.detail) hideCenterDetail();   // 详情开着 → 先关
    centerState.allinfo = true;
    ensureMask();
    // 总览模式：右栏清空（不显示当前预警点的同类对比等详细信息）
    var rli = document.querySelector('.mainbox .nav1 > li:last-child');
    var rp = rli && rli.querySelector('.detail-panel');
    if (rp) {
      rp.innerHTML = '<div class="box"><div class="tit">同类项目对比</div><div class="boxnav">' +
        '<div class="dp-empty">全部信息总览模式：已收起当前预警点详情</div></div></div>';
    }
    var all = getCenterPoints();
    centerState.list = all;
    var groups = {};
    all.forEach(function (p) {
      var d = p.district || '未分区';
      (groups[d] = groups[d] || []).push(p);
    });
    var keys = Object.keys(groups).sort(function (a, b) { return groups[b].length - groups[a].length; });
    // 头部只创建一次（输入框不被销毁，中文输入法/连续输入不会卡顿）
    if (!panel.querySelector('.cl-head')) {
      panel.innerHTML = '';   // 关键：清掉面板内残留内容（如关闭过的详情卡 cd-head/cd-body）
      var head = document.createElement('div');
      head.className = 'cl-head';
      head.innerHTML =
        '<span class="ai-title">全部信息<span class="ai-total"></span></span>' +
        '<input class="cl-search" type="text" placeholder="搜索项目 / 区县">' +
        '<div class="cl-filters">' +
        '<div class="cl-filter" data-f="all">全部</div>' +
        '<div class="cl-filter f-red" data-f="red">红</div>' +
        '<div class="cl-filter f-yellow" data-f="yellow">黄</div>' +
        '</div>' +
        '<button class="ai-close" title="关闭">×</button>';
      panel.appendChild(head);
      // 搜索绑定：input + keyup 双通道 + 输入法组合兼容（组合拼音中不过滤，避免闪烁/卡顿）
      // composing 用共享 centerState.composing——委托层 input（ensurePanel）也检查它，双通道统一
      var siEl = head.querySelector('.cl-search');
      siEl.addEventListener('compositionstart', function () { centerState.composing = true; });
      siEl.addEventListener('compositionend', function () {
        centerState.composing = false;
        centerState.q = this.value;
        scheduleFilter();
      });
      siEl.addEventListener('input', function () {
        if (centerState.composing) return;
        centerState.q = this.value;
        scheduleFilter();
      });
      siEl.addEventListener('keyup', function () {
        if (centerState.composing) return;
        centerState.q = this.value;
        scheduleFilter();
      });
    }
    // 头部状态同步（筛选高亮 + 搜索框值）
    var headEl = panel.querySelector('.cl-head');
    var si = headEl.querySelector('.cl-search');
    if (si && document.activeElement !== si) si.value = centerState.q || '';
    headEl.querySelectorAll('.cl-filter').forEach(function (f) {
      f.classList.toggle('active', f.getAttribute('data-f') === centerState.filter);
    });
    // 网格卡片排版：每区县一块，块内多列卡片（名称+徽章+跳转地图），不写详细字段；
    // 全部渲染（含折叠分组），显隐交给 applyFilter / 折叠逻辑
    var bodyHtml = '<div class="cl-body">';
    var gi = 0;
    keys.forEach(function (k) {
      var items = groups[k];
      var open = centerState.open[k] !== false;
      bodyHtml += '<div class="cl-group' + (open ? ' open' : '') + '" data-d="' + esc(k) + '">' +
        '<div class="cl-group-head" data-d="' + esc(k) + '">' +
        '<span class="cl-arrow">' + (open ? '▾' : '▸') + '</span>' +
        '<span class="cl-district">' + esc(k) + '</span>' +
        '<span class="cl-total">共 ' + items.length + ' 条</span>' +
        '</div>' +
        '<div class="ai-grid"' + (open ? '' : ' style="display:none"') + '">';
      items.forEach(function (p) {
        var cls = p.category === 'red' ? 'red' : 'yellow';
        bodyHtml += '<div class="cl-item ai-card' + (centerState.selected === gi ? ' selected' : '') + '" data-i="' + gi + '" data-cat="' + cls + '" data-name="' + esc((p.name || '').toLowerCase()) + '" data-district="' + esc((p.district || '').toLowerCase()) + '" title="' + esc(p.name || '') + '">' +
          '<div class="ai-top">' +
          '<span class="cl-dot ' + cls + '"></span>' +
          '<span class="ai-name">' + esc(p.name || '') + '</span>' +
          '</div>' +
          '<div class="ai-meta">' + esc(p.district || '') + ' · ' + esc(p.project_type || '') + ' · ' + esc(p.stage || '') + '</div>' +
          '</div>';
        gi++;
      });
      bodyHtml += '</div></div>';
    });
    bodyHtml += '</div>';
    var oldBody = panel.querySelector('.cl-body');
    if (oldBody) oldBody.remove();
    panel.insertAdjacentHTML('beforeend', bodyHtml);
    panel.classList.remove('detail');
    panel.classList.add('allinfo');
    panel.style.display = 'flex';
    applyFilter();   // 首次应用当前搜索/筛选（窗口重开时保留状态）
  }
  // 搜索防抖：输入过程中的高频事件 150ms 内只执行一次过滤（输入完全不卡，停顿后才过滤）
  var filterTimer = null;
  function scheduleFilter() {
    if (filterTimer) return;
    filterTimer = setTimeout(function () {
      filterTimer = null;
      applyFilter();
    }, 150);
  }

  // 轻量过滤：搜索词/红黄筛选只切换卡片与分组的显隐，不重建 DOM
  function applyFilter() {
    var panel = document.getElementById('center-list');
    if (!panel || !panel.classList.contains('allinfo')) return;
    if (!panel.querySelector('.cl-group')) return;   // 中央详情等其他形态不处理
    var q = (centerState.q || '').trim().toLowerCase();
    var visible = 0;
    panel.querySelectorAll('.cl-group').forEach(function (g) {
      var vis = 0;
      g.querySelectorAll('.cl-item').forEach(function (c) {
        var hit = true;
        var cat = c.getAttribute('data-cat');
        if (centerState.filter === 'red' && cat !== 'red') hit = false;
        if (centerState.filter === 'yellow' && cat !== 'yellow') hit = false;
        if (hit && q) {
          var nm = c.getAttribute('data-name') || '';
          var ds = c.getAttribute('data-district') || '';
          if (nm.indexOf(q) < 0 && ds.indexOf(q) < 0) hit = false;
        }
        c.style.display = hit ? '' : 'none';
        if (hit) vis++;
      });
      var open = centerState.open[g.getAttribute('data-d')] !== false;
      if (!vis) {
        g.style.display = 'none';
      } else {
        g.style.display = '';
        var grid = g.querySelector('.ai-grid');
        if (grid) grid.style.display = open ? '' : 'none';
        visible += vis;
      }
    });
    var totEl = panel.querySelector('.ai-total');
    if (totEl) totEl.textContent = '共 ' + visible + ' 条';
    var empty = panel.querySelector('.cl-empty');
    if (!visible && !empty) {
      var b = panel.querySelector('.cl-body');
      if (b) b.insertAdjacentHTML('beforeend', '<div class="cl-empty">无匹配项目</div>');
    } else if (visible && empty) {
      empty.remove();
    }
  }
  // 全部信息点卡片 → 窗口原地变成该项目的详细信息（中央弹窗形态，含「跳转地图」）
  function showCardDetail(p) {
    var panel = ensurePanel();
    if (!panel) return;
    var m = matchDetail(p);
    centerState.cardDetail = p;
    panel.classList.remove('detail');
    panel.classList.add('allinfo');
    panel.style.display = 'flex';
    panel.innerHTML = buildDetailHtml(p, m) +
      '<div class="cd-actions">' +
      '<button class="cd-back">返回列表</button>' +
      '<div class="cd-jump" title="关闭窗口并定位到地图上的项目">跳转地图</div>' +
      '</div>';
  }
  function hideAllInfo() {
    centerState.allinfo = false;
    centerState.cardDetail = null;
    var mask = document.getElementById('center-mask');
    if (mask) mask.remove();
    var panel = document.getElementById('center-list');
    if (panel) {
      panel.classList.remove('allinfo');
      panel.style.display = 'none';
    }
    // 关闭全部信息后恢复之前的具体预警点详情（底部上滑窗口）
    if (centerState.prevDetail) {
      var pd = centerState.prevDetail;
      centerState.prevDetail = null;
      showCenterDetail(pd);
    }
  }

  // 返回按钮统一使用 3D 的"全市地图"按钮（drill-back）：2D 打开时由 _updateDrillBackBtn 显示，
  // 点击先退出 2D 再返回全市，避免与 2D 旧"返回 3D"按钮重叠
  function syncBackButton() {
    if (window.yantaiMapChart && window.yantaiMapChart._updateDrillBackBtn) {
      window.yantaiMapChart._updateDrillBackBtn();
    }
  }

  // 按坐标找预警点（3D 图钉/2D 标记共用 map_points 坐标，0.0001° 精度）
  function findPointByLngLat(lng, lat) {
    var pts = (window.DASHBOARD_DATA && window.DASHBOARD_DATA.map_points) || [];
    for (var i = 0; i < pts.length; i++) {
      var v = pts[i] && pts[i].value;
      if (v && v.length >= 2 && Math.abs(v[0] - lng) < 0.0001 && Math.abs(v[1] - lat) < 0.0001) return pts[i];
    }
    return null;
  }

  // ---------- 对外 API ----------
  // detail（可选，兼容旧调用）= { src, row, data }；弹卡不依赖它——按坐标自匹配预警点
  function show(lng, lat, zoom, detail) {
    ensureMap().then(function () {
      // 进入 2D：让 3D 捕获当前状态（返回时定位回选中区县）
      if (window.GaodeMap2D.onEnter) window.GaodeMap2D.onEnter();
      var el = document.getElementById('map2d');
      if (el) el.style.display = 'block';
      syncBackButton();
      if (map) {
        map.invalidateSize();
        addMarkers();   // 每次打开重建标记：与 3D 图钉同源最新数据，2D/3D 一致
        if (lng !== undefined && lat !== undefined) {
          flyToPointUp([lat, lng], zoom || 16);
        }
      }
      // 展现所有信息：按坐标匹配预警点（任何入口生效），flyTo 结束后弹底部详情页；
      // 双保险：moveend 若未触发（视图已在目标附近等场景），1.5s 兜底弹出；同时渲染左右情报面板
      if (lng !== undefined && lat !== undefined) {
        var pt = findPointByLngLat(lng, lat);
        if (pt) {
          var shown = false;
          var doShow = function () {
            if (shown) return;
            shown = true;
            showCenterDetail(pt);
            renderDetailPanels(pt);
          };
          map.once('moveend', doShow);
          setTimeout(doShow, 1500);
        }
      }
    }).catch(function () {
      console.error('[街道地图] 打开失败');
    });
  }

  function hide() {
    var el = document.getElementById('map2d');
    if (el) el.style.display = 'none';
    syncBackButton();
    hideInfoCard();
    hideCenterDetail();
    hideAllInfo();
    // 返回 3D：恢复 3D 状态（相机回位 → 定位回选中区县）
    if (window.GaodeMap2D.onExit) window.GaodeMap2D.onExit();
  }

  function isVisible() {
    var el = document.getElementById('map2d');
    return !!(el && el.style.display !== 'none');
  }

  // ---------- 模式按钮：3D 模式点击 = 返回 3D（2D 通过"详情"进入、"返回 3D"按钮退出） ----------
  function onDomReady() {
    document.querySelectorAll('.bottom-menu-item').forEach(function (btn) {
      var t = btn.querySelector('span') ? btn.querySelector('span').textContent : '';
      if (t === '柱状图' || t === '热力图' || t === '预警图') {
        btn.addEventListener('click', function () { hide(); });
      }
    });
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', onDomReady);
  } else {
    onDomReady();
  }

  // 周期切换：重建 2D 标记（与 3D 图钉一致的周期筛选）
  function refreshMarkers() {
    if (!map) return;
    addMarkers();
    // 同步刷新左栏预警列表（若打开）
    var cur = centerState.detail || null;
    if (cur && typeof renderLeftPanel === 'function') renderLeftPanel(cur);
  }

  window.GaodeMap2D = {
    init: ensureMap,
    show: show,
    hide: hide,
    isVisible: isVisible,
    openAllView: openAllView,
    refreshMarkers: refreshMarkers,
    getMap: function () { return map; },
    getMarkers: function () { return markers.slice(); },
  };
})();
