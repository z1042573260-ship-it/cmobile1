// ============================================================
// 高德街道瓦片引擎（无 key，raw 瓦片服务）
// Web Mercator (EPSG:3857) XYZ 瓦片数学 + 拉取 + 拼接 + 缓存
// 暴露 window.GaodeTiles
// ============================================================
(function () {
  'use strict';

  var TILE = 256;
  var SUBDOMAINS = ['1', '2', '3', '4'];
  var URL = 'https://webrd0{s}.is.autonavi.com/appmaptile?lang=zh_cn&size=1&scale=1&style=8&x={x}&y={y}&z={z}';
  // 卫星底图（备用，未启用）：style=6 → webst0{s}.is.autonavi.com

  var cache = new Map();   // key: 'z/x/y' → {img, promise}

  function lngLatToTile(lng, lat, z) {
    var n = Math.pow(2, z);
    var x = (lng + 180) / 360 * n;
    var latRad = lat * Math.PI / 180;
    var y = (1 - Math.asinh(Math.tan(latRad)) / Math.PI) / 2 * n;
    return [Math.floor(x), Math.floor(y)];
  }

  // tile 左上角经纬度
  function tileToLngLat(x, y, z) {
    var n = Math.pow(2, z);
    var lng = x / n * 360 - 180;
    var lat = Math.atan(Math.sinh(Math.PI * (1 - 2 * y / n))) * 180 / Math.PI;
    return [lng, lat];
  }

  function tileBounds(x, y, z) {
    var nw = tileToLngLat(x, y, z);
    var se = tileToLngLat(x + 1, y + 1, z);
    return { north: nw[1], west: nw[0], south: se[1], east: se[0] };
  }

  // bbox(经纬度) 在 z 级覆盖的瓦片范围
  function tileRange(minLng, maxLng, minLat, maxLat, z) {
    var nw = lngLatToTile(minLng, maxLat, z);
    var se = lngLatToTile(maxLng, minLat, z);
    var x0 = Math.min(nw[0], se[0]), x1 = Math.max(nw[0], se[0]);
    var y0 = Math.min(nw[1], se[1]), y1 = Math.max(nw[1], se[1]);
    var tilesX = x1 - x0 + 1, tilesY = y1 - y0 + 1;
    return { x0: x0, y0: y0, x1: x1, y1: y1, tilesX: tilesX, tilesY: tilesY, count: tilesX * tilesY };
  }

  // 从高往低选 z，使瓦片数 ≤ maxTiles（控制请求量/内存）
  function bestZoom(minLng, maxLng, minLat, maxLat, maxTiles) {
    for (var z = 18; z >= 1; z--) {
      var r = tileRange(minLng, maxLng, minLat, maxLat, z);
      if (r.count <= maxTiles) { r.z = z; return r; }
    }
    var r1 = tileRange(minLng, maxLng, minLat, maxLat, 1);
    r1.z = 1;
    return r1;
  }

  function tileUrl(x, y, z, sub) {
    return URL.replace('{s}', sub).replace('{x}', x).replace('{y}', y).replace('{z}', z);
  }

  function loadImage(url, timeout) {
    return new Promise(function (resolve, reject) {
      var img = new Image();
      var to = setTimeout(function () {
        img.onload = img.onerror = null;
        reject(new Error('tile timeout: ' + url));
      }, timeout || 8000);
      img.crossOrigin = 'anonymous';   // 服务器返回 Access-Control-Allow-Origin: *，可安全读
      img.onload = function () { clearTimeout(to); resolve(img); };
      img.onerror = function () { clearTimeout(to); reject(new Error('tile fail: ' + url)); };
      img.src = url;
    });
  }

  // 拉取一张瓦片（带缓存），返回 Promise<img>
  function getTile(x, y, z) {
    var key = z + '/' + x + '/' + y;
    if (cache.has(key)) return cache.get(key);
    var sub = SUBDOMAINS[(x + y) % SUBDOMAINS.length];
    var p = loadImage(tileUrl(x, y, z, sub));
    cache.set(key, p);
    return p;
  }

  // 拉取 bbox 在 z 级的瓦片并拼成一张画布
  // opts: { maxTiles, timeout }
  // 返回 Promise<{ canvas, range, z }>；瓦片数超上限自动降 z；任一张失败 reject
  function fetchStitched(minLng, maxLng, minLat, maxLat, z, opts) {
    opts = opts || {};
    var maxTiles = opts.maxTiles || 25;
    var range = tileRange(minLng, maxLng, minLat, maxLat, z);
    if (range.count > maxTiles) {
      range = bestZoom(minLng, maxLng, minLat, maxLat, maxTiles);
      z = range.z;
    }
    var tiles = [];
    for (var ty = range.y0; ty <= range.y1; ty++) {
      for (var tx = range.x0; tx <= range.x1; tx++) {
        tiles.push({ x: tx, y: ty, p: getTile(tx, ty, z) });
      }
    }
    return Promise.all(tiles.map(function (t) { return t.p; })).then(function (imgs) {
      var canvas = document.createElement('canvas');
      canvas.width = range.tilesX * TILE;
      canvas.height = range.tilesY * TILE;
      var ctx = canvas.getContext('2d');
      tiles.forEach(function (t, i) {
        ctx.drawImage(imgs[i], (t.x - range.x0) * TILE, (t.y - range.y0) * TILE, TILE, TILE);
      });
      return { canvas: canvas, range: range, z: z };
    });
  }

  // 瓦片 → 经纬度边界（供贴图定位/遮罩）
  function rangeBounds(range, z) {
    var nw = tileToLngLat(range.x0, range.y0, z);
    var se = tileToLngLat(range.x1 + 1, range.y1 + 1, z);
    return { west: nw[0], north: nw[1], east: se[0], south: se[1] };
  }

  function clearCache() { cache.clear(); }

  window.GaodeTiles = {
    lngLatToTile: lngLatToTile,
    tileToLngLat: tileToLngLat,
    tileBounds: tileBounds,
    tileRange: tileRange,
    bestZoom: bestZoom,
    getTile: getTile,
    fetchStitched: fetchStitched,
    rangeBounds: rangeBounds,
    clearCache: clearCache,
    TILE: TILE,
  };
})();
