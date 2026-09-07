// 工程建设信息自动化预警平台 - 数据驱动图表
$(window).load(function() { $(".loading").fadeOut(); });

var chartInstances = {};

// ===== 区县预警排名图（echart2）横坐标可手动调整参数（改数字保存刷新即生效）=====
var E2_AXIS_ROTATE = 30;     // 标签旋转角度（0=横排不斜；30=向右斜 30°。本周/本月/今年统一）
var E2_GRID_BOTTOM = 17;     // 横坐标底部留白 px（角度越大留白越多，46 适合 30°）

// 区县预警数据周期状态（本周/本月/今年）
var _mqPeriod = 'week';
// 暴露当前周期（three-map 返回全市/模式切换时取导航栏周期，防止用错 _pinPeriod 显示全量数据）
window.getMqPeriod = function() { return _mqPeriod; };
// 按发布日（publish_date，YYYY-MM-DD）过滤项目列表
function filterByPeriod(pl, period) {
    var now = new Date();
    var y = now.getFullYear();
    var mm = now.getMonth() + 1;
    var m = mm < 10 ? '0' + mm : String(mm);
    // 自然周（周一起）：回到本周一（与 periodStartStr/isThisWeek 口径一致）
    var wsDate = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    var wday = wsDate.getDay();
    wsDate.setDate(wsDate.getDate() + (wday === 0 ? -6 : 1 - wday));
    var wm = wsDate.getMonth() + 1;
    var wd = wsDate.getDate();
    var ws = wsDate.getFullYear() + '-' + (wm < 10 ? '0' + wm : wm) + '-' + (wd < 10 ? '0' + wd : wd);
    var monthKey = y + '-' + m;
    var yearKey = String(y);
    var out = [];
    for (var i = 0; i < pl.length; i++) {
        var p = pl[i];
        var dd = String(p.date || '');
        if (!dd) continue;
        dd = dd.replace(/\./g, '-');   // 防御：点号式日期（2026.02.06）统一横杠再比较
        if (period === 'year' && dd.indexOf(yearKey) === 0) out.push(p);
        else if (period === 'month' && dd.indexOf(monthKey) === 0) out.push(p);
        else if (period === 'week' && dd >= ws) out.push(p);
    }
    return out;
}

// 统计口径区县归一（用户要求 2026-08-21）：开发区（功能区，地理在福山境内）项目计入福山区；
// 柱状图（buildDistrictRanking）保持开发区独立显示，不经过此映射
function statDistrict(d) {
    if (d === '开发区' || d === '烟台开发区') return '福山区';
    if (d === '长岛综合试验区' || d === '长岛县' || d === '长岛综试区') return '蓬莱区';
    return d;
}

// ====== 施工道路周期过滤（交底日期 jiaodi_date：'YYYY.M.D' / 'YY.M.D' / 'YYYY-M-D'） ======
// 本周=自然周（周一起）至今天、本月=当月、今年=当年；无有效日期/未来日期 → 不计入
window.filterWorkByPeriod = function (roads, period) {
    var now = new Date();
    var today = now.getFullYear() * 10000 + (now.getMonth() + 1) * 100 + now.getDate();
    var ws = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    var wday = ws.getDay();
    ws.setDate(ws.getDate() + (wday === 0 ? -6 : 1 - wday));
    var wsKey = ws.getFullYear() * 10000 + (ws.getMonth() + 1) * 100 + ws.getDate();
    var y = now.getFullYear(), ym = y * 100 + (now.getMonth() + 1);
    function dkey(r) {
        var s = String(r.jiaodi_date || '').trim();
        if (!s) return null;
        s = s.replace(/[.\-\/]/g, '-');
        var ps = s.split('-').map(function (x) { return parseInt(x, 10); });
        if (ps.length < 3 || !ps[0] || !ps[1] || !ps[2]) return null;
        var yy = ps[0] < 100 ? 2000 + ps[0] : ps[0];
        if (yy < 2000 || yy > 2100) return null;
        return yy * 10000 + ps[1] * 100 + ps[2];
    }
    return (roads || []).filter(function (r) {
        var k = dkey(r);
        if (k === null || k > today) return false;
        if (period === 'year') return Math.floor(k / 10000) === y;
        if (period === 'month') return Math.floor(k / 100) === ym;
        return k >= wsKey;
    });
};
// 施工图按周期过滤后按区县计数（3D 施工柱高/标签数字 + 2D 列表/线共用）
window.buildWorkDistrictRanking = function (period) {
    var eng = window.ENGINEERING_DATA || {};
    var list = (window.filterWorkByPeriod ? window.filterWorkByPeriod(eng.roads || [], period) : eng.roads) || [];
    var m = {};
    list.forEach(function (r) { if (!r || !r.district) return; m[r.district] = (m[r.district] || 0) + 1; });
    return Object.keys(m).map(function (k) { return { name: k, value: m[k] }; })
        .sort(function (a, b) { return b.value - a.value; });
};

// 按周期过滤 project_list 后按区县分组（3D 柱状图柱高/柱顶数字随周期变化）
function buildDistrictRanking(period) {
    var pl = filterByPeriod((getData().project_list || []), period);
    var m = {};
    pl.forEach(function (p) {
        if (!p || !p.district) return;
        var k = statDistrict(p.district);   // 统计口径：长岛→蓬莱区、开发区→福山区（与 echart2 一致）
        m[k] = (m[k] || 0) + 1;
    });
    return Object.keys(m).map(function (k) { return { name: k, value: m[k] }; })
        .sort(function (a, b) { return b.value - a.value; });
}

// 按周期过滤 project_list 后分组统计（field: 'type' | 'stage'，stage 已由导出归档为 5 类）
function buildPeriodPie(field) {
    var d = getData();
    var pl = filterByPeriod(d.project_list || [], _mqPeriod);
    var tcount = {};
    for (var i = 0; i < pl.length; i++) {
        var p = pl[i];
        if (!p || !p[field]) continue;
        tcount[p[field]] = (tcount[p[field]] || 0) + 1;
    }
    return Object.keys(tcount).map(function (k) { return { name: k, value: tcount[k] }; })
        .sort(function (a, b) { return b.value - a.value; });
}

// 获取大屏数据（数据加载失败 → 空结构，不伪造假数据）
function getData() {
    return window.DASHBOARD_DATA || {
        summary: { total: 0, red_warning: 0, yellow_warning: 0, district_count: 0 },
        district_ranking: [],
        timeline: [],
        red_timeline: [],
        yellow_timeline: [],
        warning_pie: [],
        type_pie: [],
        stage_pie: [],
        map_points: [],
        project_list: []
    };
}

// ====== Echart2: 区县施工数据（干线红/骨干汇聚橙/其他黄 堆叠柱，样式沿用原预警柱图） ======
// 数据源 = ENGINEERING_DATA.roads（交底日期按周期过滤），固定列出烟台 13 区县（无数据为 0）
function initWorkEchart2() {
    var dom = document.getElementById('echart2');
    if (!dom) return;
    var roads = workRoadsOf(_mqPeriod, _drillDistrict || null);
    var byDist = {};
    WORK_DISTRICTS.forEach(function (d) { byDist[d] = { trunk: 0, hub: 0, other: 0 }; });
    roads.forEach(function (r) {
        if (!r || !r.district) return;
        var b = byDist[r.district];
        if (!b) return;
        var lv = String(r.level || '');
        if (lv.indexOf('红') >= 0) b.trunk++;
        else if (lv.indexOf('橙') >= 0) b.hub++;
        else b.other++;
    });
    var names = WORK_DISTRICTS.slice();
    var trunkData = [], hubData = [], otherData = [];
    names.forEach(function (d) {
        trunkData.push(byDist[d].trunk);
        hubData.push(byDist[d].hub);
        otherData.push(byDist[d].other);
    });
    var totalData = trunkData.map(function (v, i) { return v + hubData[i] + otherData[i]; });
    var hasAny = totalData.some(function (v) { return v > 0; });
    if (chartInstances.echart2) { chartInstances.echart2.dispose(); chartInstances.echart2 = null; }
    if (!hasAny) {
        dom.innerHTML = '<div style="height:100%;display:flex;align-items:center;justify-content:center;color:rgba(255,255,255,.5);font-size:13px;">该周期暂无施工数据</div>';
        return;
    }
    var myChart = echarts.init(dom);
    chartInstances.echart2 = myChart;
    myChart.setOption({
        tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' },
            formatter: function(ps) {
                var s = '<div style="color:rgba(255,255,255,.85);font-size:12px;">' + ps[0].axisValue + '</div>';
                for (var k = 0; k < ps.length; k++) {
                    s += '<div style="font-size:11px;"><span style="display:inline-block;width:8px;height:8px;border-radius:2px;background:' + ps[k].color + ';margin-right:4px;"></span>' +
                        ps[k].seriesName + ' <b style="float:right;margin-left:10px;">' + ps[k].value + '</b></div>';
                }
                return s;
            } },
        legend: {
            bottom: 0, itemWidth: 10, itemHeight: 10, textStyle: { color: 'rgba(255,255,255,.6)', fontSize: 10 },
            data: ['干线', '骨干汇聚', '其他']
        },
        grid: { left: '0', top: '22', right: '0', bottom: E2_GRID_BOTTOM, containLabel: true },
        xAxis: {
            type: 'category', data: names,
            axisLine: { lineStyle: { color: 'rgba(255,255,255,.3)' } },
            axisTick: { show: false },
            axisLabel: { interval: 0, fontSize: 11, color: '#fff',
                rotate: E2_AXIS_ROTATE,
                formatter: function(v) {
                    return v.replace('开发区(黄渤海新区)', '黄渤海').replace(/区$/, '').replace(/市$/, '');
                } }
        },
        yAxis: {
            type: 'value',
            interval: function(v) { return Math.max(1, Math.ceil(v.max / 6)); },
            max: function(v) { return Math.ceil(v.max); },
            axisLine: { show: false }, axisTick: { show: false },
            splitLine: { lineStyle: { color: 'rgba(255,255,255,.1)' } },
            axisLabel: { textStyle: { color: 'rgba(255,255,255,.85)', fontSize: 14 } }
        },
        series: [{
            name: '干线', type: 'bar', stack: 'total',
            data: trunkData, barWidth: 9,
            itemStyle: { normal: { color: '#ff385c' } }
        }, {
            name: '骨干汇聚', type: 'bar', stack: 'total',
            data: hubData, barWidth: 9,
            itemStyle: { normal: { color: '#ff8a3d' } }
        }, {
            name: '其他', type: 'bar', stack: 'total',
            data: otherData, barWidth: 9,
            itemStyle: { normal: { color: '#ffd23d', barBorderRadius: [2, 2, 0, 0] } },
            label: { normal: { show: true, position: 'top', distance: 1,
                formatter: function(pp) { return totalData[pp.dataIndex] > 0 ? totalData[pp.dataIndex] : ''; },
                textStyle: { color: '#ffffff', fontSize: 14, fontWeight: 'bold' } } }
        }]
    });
}

// 周期起点（YYYY-MM-DD 字符串）：本周=周一起、本月=1号、今年=1月1日（保留给其它调用）
function periodStartStr(period) {
    var now = new Date();
    if (period === 'week') {
        var d = new Date(now.getFullYear(), now.getMonth(), now.getDate());
        var day = d.getDay();
        var diff = (day === 0 ? -6 : 1 - day);
        d.setDate(d.getDate() + diff);
        return d.getFullYear() + '-' + pad2(d.getMonth() + 1) + '-' + pad2(d.getDate());
    }
    if (period === 'month') return now.getFullYear() + '-' + pad2(now.getMonth() + 1) + '-01';
    if (period === 'year') return now.getFullYear() + '-01-01';
    return '';
}
function pad2(n) { return n < 10 ? '0' + n : String(n); }

// ====== 施工交底趋势数据（总数 + 干线 + 骨干汇聚，按交底日期 jiaodi_date） ======
function buildWorkTimeline(period) {
    var roads = workRoadsOf(period, _drillDistrict || null);
    var now = new Date();
    var buckets = {}, order = [];
    function jKey(r) {
        var s = String(r.jiaodi_date || '');
        s = s.replace(/[.\-\/]/g, '-');
        var ps = s.split('-');
        if (ps.length < 3) return '';
        var yy = parseInt(ps[0], 10);
        if (yy < 100) yy += 2000;
        var mm = parseInt(ps[1], 10), dd = parseInt(ps[2], 10);
        if (!yy || !mm || !dd) return '';
        return yy + '-' + pad2(mm) + '-' + pad2(dd);
    }
    var fmtKey;
    if (period === 'week') {
        fmtKey = function (d) { return d.slice(0, 10); };
        for (var i = 6; i >= 0; i--) {
            var t = new Date(now.getTime() - i * 86400000);
            var k = t.getFullYear() + '-' + pad2(t.getMonth() + 1) + '-' + pad2(t.getDate());
            buckets[k] = { total: 0, trunk: 0, hub: 0 }; order.push(k);
        }
    } else if (period === 'month') {
        fmtKey = function (d) { return d.slice(0, 10); };
        var ym = now.getFullYear() + '-' + pad2(now.getMonth() + 1);
        for (var j = 1; j <= now.getDate(); j++) {
            var k2 = ym + '-' + pad2(j);
            buckets[k2] = { total: 0, trunk: 0, hub: 0 }; order.push(k2);
        }
    } else {
        fmtKey = function (d) { return d.slice(0, 7); };
        var y = String(now.getFullYear());
        for (var m = 1; m <= now.getMonth() + 1; m++) {
            var k3 = y + '-' + pad2(m);
            buckets[k3] = { total: 0, trunk: 0, hub: 0 }; order.push(k3);
        }
    }
    roads.forEach(function (r) {
        var dd = jKey(r);
        if (!dd) return;
        var key = fmtKey(dd);
        if (!buckets[key]) return;
        buckets[key].total++;
        var lv = String(r.level || '');
        if (lv.indexOf('红') >= 0) buckets[key].trunk++;
        else if (lv.indexOf('橙') >= 0) buckets[key].hub++;
    });
    var out = { timeline: [], trunk_timeline: [], hub_timeline: [] };
    order.forEach(function (k) {
        out.timeline.push({ date: k, value: buckets[k].total });
        out.trunk_timeline.push({ date: k, value: buckets[k].trunk });
        out.hub_timeline.push({ date: k, value: buckets[k].hub });
    });
    return out;
}

// ====== Echart3: 施工交底趋势 (三线: 交底总数 + 干线 + 骨干汇聚，随周期动态计算) ======
function initWorkEchart3() {
    var dom = document.getElementById('echart3');
    if (!dom) return;
    var tl = buildWorkTimeline(_mqPeriod);
    var timeline = tl.timeline;
    var trunkTL = tl.trunk_timeline;
    var hubTL = tl.hub_timeline;
    var dates = [];
    for (var i = 0; i < timeline.length; i++) { dates.push(timeline[i].date); }
    if (chartInstances.echart3) { chartInstances.echart3.dispose(); chartInstances.echart3 = null; }
    var myChart = echarts.init(dom);
    chartInstances.echart3 = myChart;
    myChart.setOption({
        tooltip: { trigger: 'axis' },
        legend: {
            bottom: 0, textStyle: { color: 'rgba(255,255,255,.6)', fontSize: 10 },
            data: [
                { name: '交底总数', textStyle: { color: '#37a2da' } },
                { name: '干线', textStyle: { color: '#ff4444' } },
                { name: '骨干汇聚', textStyle: { color: '#ff8a3d' } }
            ]
        },
        grid: { left: '5', top: '10', right: '10', bottom: '25', containLabel: true },
        xAxis: {
            type: 'category', boundaryGap: false, data: dates,
            axisLabel: { textStyle: { color: 'rgba(255,255,255,.5)', fontSize: 10 } },
            axisLine: { lineStyle: { color: 'rgba(255,255,255,.2)' } }
        },
        yAxis: {
            type: 'value', axisTick: { show: false }, splitNumber: 3,
            axisLine: { show: false },
            axisLabel: { textStyle: { color: 'rgba(255,255,255,.5)', fontSize: 10 } },
            splitLine: { lineStyle: { color: 'rgba(255,255,255,.1)', type: 'dotted' } }
        },
        series: [{
            name: '交底总数', type: 'line', smooth: true, symbol: 'circle', symbolSize: 4,
            itemStyle: { color: '#37a2da' },
            lineStyle: { color: '#37a2da', width: 3 },
            areaStyle: { color: 'rgba(55,162,218,0.25)' },
            data: timeline.map(function(d) { return d.value; })
        }, {
            name: '干线', type: 'line', smooth: true, symbol: 'circle', symbolSize: 4,
            itemStyle: { color: '#ff4444' },
            lineStyle: { color: '#ff4444', width: 3 },
            data: trunkTL.map(function(d) { return d.value; })
        }, {
            name: '骨干汇聚', type: 'line', smooth: true, symbol: 'circle', symbolSize: 4,
            itemStyle: { color: '#ff8a3d' },
            lineStyle: { color: '#ff8a3d', width: 3 },
            data: hubTL.map(function(d) { return d.value; })
        }]
    });
}


// ====== Marquee: 抓取日志（原版平滑滚动 + 翻页条控制滚动偏移 + 全部→2D 地图） ======
var _mqTimer = null;
var _mqIndex = 0;

function initMarquee() {
    var dom = document.getElementById('marqueeRed');
    if (!dom) return;
    var list = dom.querySelector('.marquee-list');
    if (!list) return;

    // ===== 日志按地图模式：柱状图/预警图 = 预警抓取日志（原版）；施工图 = 施工日志 =====
    var isWork = leftPanelMode() === 'work';
    var items = [];
    if (isWork) {
        // 施工日志：当前周期施工道路（交底日期倒序）
        items = workRoadsOf(_mqPeriod, null).slice().sort(function (a, b) {
            return String(b.jiaodi_date).localeCompare(String(a.jiaodi_date));
        });
    } else {
        // 预警抓取日志（原版）：map_points 按坐标去重
        var d = getData();
        var seen = {};
        (d.map_points_original || []).concat(d.map_points || []).forEach(function (p) {
            if (!p || !p.value || p.value.length < 2) return;
            var key = Math.round(p.value[0] * 1e4) + ',' + Math.round(p.value[1] * 1e4);
            if (seen[key]) return;
            seen[key] = true;
            items.push(p);
        });
    }
    if (items.length === 0) {
        list.innerHTML = '<li><span class="mq-time">--</span>' +
            (isWork ? '该周期暂无施工项目' : '暂无抓取数据') + '</li>';
        return;
    }

    // 构建列表 HTML（全部条目，滚动用 transform）
    var html = '';
    for (var i = 0; i < items.length; i++) {
        var p = items[i];
        var tagClass = '', tagText = '';
        var time = '', status = '';
        if (isWork) {
            var lv = String(p.level || '');
            if (lv.indexOf('红') >= 0) { tagClass = 'red'; tagText = '干线'; }
            else if (lv.indexOf('橙') >= 0) { tagClass = 'orange'; tagText = '骨干'; }
            else { tagClass = 'yellow'; tagText = '其他'; }
            var date = String(p.jiaodi_date || '');
            time = date.replace(/^\d{4}\./, '').replace(/^\d{2}\./, '') || '—';   // '2026.8.24' → '8.24'
            status = p.status || '—';
        } else {
            var warning = p.warning || '';
            if (warning === '红色预警') { tagClass = 'red'; tagText = '红警'; }
            else if (warning === '黄色预警') { tagClass = 'yellow'; tagText = '黄警'; }
            else { tagClass = 'blue'; tagText = '成功'; }
            var date2 = p.date || '';
            time = date2.length > 5 ? date2.substring(date2.length - 5, date2.length) : date2;
            status = p.stage || '—';
        }
        var name = String(p.road || p.name || '').substring(0, 26);
        var district = p.district || '';

        html += '<li data-idx="' + i + '">';
        html += '<span class="mq-time">' + time + '</span>';
        html += '<span class="tag ' + tagClass + '">' + tagText + '</span>';
        html += '<span class="mq-district">[' + district + ']</span>';
        html += '<span class="mq-name">' + name + '</span>';
        html += '<span class="mq-status">' + status + '</span>';
        html += '</li>';
    }
    list.innerHTML = html;

    // 点击日志条目：work=切施工 2D 定位该路；预警/柱状图=切 3D 预警图聚焦该图钉（原版）
    if (dom._mqClick) dom.removeEventListener('click', dom._mqClick);
    var clickHandler = function (e) {
        try {
            var li = e.target && e.target.closest ? e.target.closest('li[data-idx]') : null;
            if (!li) return;
            var idx = parseInt(li.getAttribute('data-idx'), 10);
            var p = items[idx];
            if (!p) return;
            if (leftPanelMode() === 'work') {
                var m = window.yantaiMapChart;
                if (m && m._mapMode !== 'work') {
                    try { m.setMapMode('work'); } catch (err) { console.error('mode:', err); }
                }
                if (window.WorkMap2D && window.WorkMap2D.focusRoad) {
                    window.WorkMap2D.focusRoad(p);
                }
            } else {
                // 原版预警：点击时用当前 map_points 重匹配（前缀匹配，容忍名称截断/数据刷新差异）
                var cur = (window.DASHBOARD_DATA && window.DASHBOARD_DATA.map_points) || [];
                var pn0 = String(p.name || '').trim();
                for (var k = 0; k < cur.length; k++) {
                    var cn = cur[k] && String(cur[k].name || '').trim();
                    if (!cn) continue;
                    if (cn === pn0 || (pn0.length > 4 && cn.indexOf(pn0) === 0) || (pn0.length > 4 && pn0.indexOf(cn) === 0)) {
                        p = cur[k];
                        break;
                    }
                }
                if (window.GaodeMap2D && window.GaodeMap2D.isVisible && window.GaodeMap2D.isVisible()) {
                    window.GaodeMap2D.hide();
                }
                var m2 = window.yantaiMapChart;
                if (m2 && m2.focusWarningPin) {
                    m2.focusWarningPin({ name: p.name, district: p.district });
                }
            }
        } catch (err) {
            console.error('[日志点击] 异常:', err);
        }
    };
    dom._mqClick = clickHandler;
    dom.addEventListener('click', clickHandler);

    // 滚动参数（原版逻辑）
    var itemHeight = 32;        // li 高度
    var visibleRows = Math.floor(dom.clientHeight / itemHeight);
    var totalRows = items.length;
    var maxScroll = Math.max(0, (totalRows - visibleRows) * itemHeight);
    var pageSize = itemHeight * visibleRows;   // 每页滚动像素
    var totalPages = Math.max(1, Math.floor(maxScroll / pageSize) + 1);
    var page = 1;
    _mqIndex = 0;

    var pageEl = document.getElementById('mqPage');
    var prevEl = document.getElementById('mqPrev');
    var nextEl = document.getElementById('mqNext');
    var allEl = document.getElementById('mqAll');

    function updatePage() {
        if (pageEl) pageEl.textContent = page + '/' + totalPages;
        if (prevEl) prevEl.disabled = page <= 1;
        if (nextEl) nextEl.disabled = page >= totalPages;
    }

    function scrollTo(offset) {
        list.style.transition = 'none';
        list.style.transform = 'translateY(-' + offset + 'px)';
        list.offsetHeight;   // 强制回流
        list.style.transition = 'transform 0.5s ease';
    }

    function jumpToPage(p) {
        page = Math.min(Math.max(1, p), totalPages);
        var offset = Math.min((page - 1) * pageSize, maxScroll);
        _mqIndex = Math.round(offset / itemHeight);
        scrollTo(offset);
        updatePage();
    }

    // 自动滚动（原版：每 2s 滚一行，滚完无缝回弹顶部循环）
    function scrollOne() {
        _mqIndex++;
        if (_mqIndex > totalRows) {
            _mqIndex = 0;
            scrollTo(0);
            page = 1;
            updatePage();
            return;
        }
        var offset = Math.min(_mqIndex * itemHeight, maxScroll);
        list.style.transform = 'translateY(-' + offset + 'px)';
        var p = Math.floor(offset / pageSize) + 1;
        if (p !== page) { page = p; updatePage(); }
    }

    function startScroll() {
        stopScroll();
        _mqTimer = setInterval(scrollOne, 2000);
    }
    function stopScroll() {
        if (_mqTimer) { clearInterval(_mqTimer); _mqTimer = null; }
    }
    dom.addEventListener('mouseenter', stopScroll);
    dom.addEventListener('mouseleave', startScroll);

    if (prevEl) prevEl.onclick = function () { if (page > 1) jumpToPage(page - 1); };
    if (nextEl) nextEl.onclick = function () { if (page < totalPages) jumpToPage(page + 1); };
    if (allEl) allEl.onclick = function () {
        // work=施工图 2D 全区 + 中央"全部道路"窗口；预警/柱状图=原预警 2D 全部视图
        if (leftPanelMode() === 'work') {
            var m = window.yantaiMapChart;
            if (m && m._mapMode !== 'work') {
                try { m.setMapMode('work'); } catch (e) { console.error('mode:', e); }
            }
            if (window.GaodeMap2D && window.GaodeMap2D.isVisible && window.GaodeMap2D.isVisible()) {
                try { window.GaodeMap2D.hide(); } catch (e) {}
            }
            if (window.WorkMap2D) {
                window.WorkMap2D.show(120.78, 37.25, 11);
                var t0 = Date.now();
                var waitTimer = setInterval(function () {
                    if (window.WorkMap2D.getMap && window.WorkMap2D.getMap()) {
                        clearInterval(waitTimer);
                        try { window.WorkMap2D.showAllRoadsWindow(); } catch (e) { console.error('all win:', e); }
                    } else if (Date.now() - t0 > 12000) {
                        clearInterval(waitTimer);
                    }
                }, 300);
            }
        } else if (window.GaodeMap2D && window.GaodeMap2D.openAllView) {
            window.GaodeMap2D.openAllView();
        }
    };

    updatePage();
    startScroll();
}

// ====== Echart5: 项目类型 (玫瑰饼图) ======
// ====== Echart5: 项目类型分布 (玫瑰饼) ======
// 下钻区县时按该区县过滤统计（3D 地图 _switchDistrict/_switchCity 回调 onDistrictDrill）
var _drillDistrict = null;   // 当前下钻区县（null=全市）
var _typeFilter = null;      // 项目类型筛选（点击 echart5 扇区切换）
var _stageFilter = null;     // 项目阶段筛选（点击 echart6 柱子切换）

function districtEq(name, pd) {
    if (!name || !pd) return false;
    if (pd === name) return true;
    if (pd.indexOf(name) >= 0 || name.indexOf(pd) >= 0) return true;
    return false;
}

function buildTypeStage(districtName) {
    var d = getData();
    // 下钻类型/阶段同样按导航栏周期过滤（周期为第一优先级，与全市一致）
    var pl = filterByPeriod(d.project_list || [], _mqPeriod);
    var tCount = {}, sCount = {};
    for (var i = 0; i < pl.length; i++) {
        var p = pl[i];
        // 统计口径：下钻福山区时开发区项目计入
        if (districtName && !districtEq(districtName, statDistrict(p.district))) continue;
        var t = p.type || '其他';
        var s = p.stage || '其他';
        tCount[t] = (tCount[t] || 0) + 1;
        sCount[s] = (sCount[s] || 0) + 1;
    }
    var typePie = [];
    for (var tk in tCount) typePie.push({ name: tk, value: tCount[tk] });
    typePie.sort(function(a, b) { return b.value - a.value; });
    var stagePie = [];
    for (var sk in sCount) stagePie.push({ name: sk, value: sCount[sk] });
    return { type_pie: typePie, stage_pie: stagePie };
}

function renderDistrictCharts(districtName) {
    _drillDistrict = districtName || null;
    try {
        if (chartInstances.echart5) { chartInstances.echart5.dispose(); chartInstances.echart5 = null; }
        if (chartInstances.echart6) { chartInstances.echart6.dispose(); chartInstances.echart6 = null; }
        initEchart5();
        initEchart6();
        updateStatPanel();   // 预警实时统计跟随下钻区县
    } catch(e) { console.error('district charts:', e); }
}
window.onDistrictDrill = function(name) { renderDistrictCharts(name); };

// ====== 施工统计（替代预警统计：干线/骨干汇聚/其他；跟随下钻区县 + 当前周期） ======
var WORK_DISTRICTS = ['芝罘区', '福山区', '牟平区', '莱山区', '蓬莱区', '龙口市', '莱阳市',
    '莱州市', '招远市', '栖霞市', '海阳市', '开发区', '高新区'];
function workRoadsOf(period, districtName) {
    var eng = window.ENGINEERING_DATA || {};
    var roads = (window.filterWorkByPeriod ? window.filterWorkByPeriod(eng.roads || [], period) : eng.roads) || [];
    if (districtName) {
        roads = roads.filter(function (r) { return r && districtEq(districtName, r.district); });
    }
    return roads;
}
// 级别计数：干线（红）/骨干汇聚（橙）/其他（黄）
function workLevelCounts(period, districtName) {
    var c = { trunk: 0, hub: 0, other: 0 };
    workRoadsOf(period, districtName).forEach(function (r) {
        var lv = String(r.level || '');
        if (lv.indexOf('红') >= 0) c.trunk++;
        else if (lv.indexOf('橙') >= 0) c.hub++;
        else c.other++;
    });
    return c;
}
// 施工实时统计：干线 / 骨干汇聚 / 其他（跟随下钻区县 + 当前周期）
function updateWorkStatPanel() {
    var c = workLevelCounts(_mqPeriod, _drillDistrict);
    var elR = document.getElementById('statRed');
    var elY = document.getElementById('statYellow');
    var elD = document.getElementById('statDistricts');
    if (elR) elR.textContent = c.trunk;
    if (elY) elY.textContent = c.hub;
    if (elD) elD.textContent = c.other;
}

function initEchart5Alert() {
    var dom = document.getElementById('echart5');
    if (!dom) return;
    // 下钻：该区县类型；非下钻：按当前周期（本周/本月/今年）过滤 project_list 后统计
    var pieData = _drillDistrict ? buildTypeStage(_drillDistrict).type_pie : buildPeriodPie('type');
    if (pieData.length === 0) {
        if (chartInstances.echart5) { chartInstances.echart5.dispose(); chartInstances.echart5 = null; }
        dom.innerHTML = '<div style="height:100%;display:flex;align-items:center;justify-content:center;color:rgba(255,255,255,.5);font-size:13px;">该周期暂无项目</div>';
        return;
    }
    if (chartInstances.echart5) { chartInstances.echart5.dispose(); chartInstances.echart5 = null; }
    var myChart = echarts.init(dom);
    chartInstances.echart5 = myChart;
    // 扇区级指示线长度：大扇区标签被推得远 → 线加长；小扇区往里收；确保所有扇区都有线
    // （今年/下钻全量数据扇区多易挤，统一收敛；海阳下钻的工业园区同样适用）
    var labelLineByType = {
        '工业厂房': { length: 10, length2: 12 },
        '工业园区': { length: 5, length2: 8 },
        '能源电力': { length: 6, length2: 10 },
        '住宅小区': { length: 3, length2: 5 },   // 恢复指示线（饼图已左移，标签不碰图例）
        '其他':     { length: 2, length2: 4 },
    };
    var pieData2 = pieData.map(function(d) {
        var ll = labelLineByType[d.name] || { length: 6, length2: 10 };
        // echarts 数据项级 labelLine 是扁平结构（不包 normal）；show:false 直接隐藏线
        return { name: d.name, value: d.value,
                 labelLine: { length: ll.length, length2: ll.length2, show: ll.show !== false } };
    });
    myChart.setOption({
        legend: { orient: 'vertical', itemWidth: 10, itemHeight: 10,
            textStyle: { color: 'rgba(255,255,255,.5)' }, top: 'center', right: 5,
            data: pieData.map(function(d) { return d.name; }) },
        color: ['#37a2da','#32c5e9','#9fe6b8','#ffdb5c','#ff9f7f','#fb7293','#e7bcf3','#8378ea','#1089E7'],
        tooltip: { trigger: 'item', formatter: "{b}: {c} ({d}%)" },
        series: [{
            // center 平衡：左侧留边界（不被卡片左缘裁剪）、右侧避图例
            type: 'pie', radius: [16, 62], center: ['31%', '50%'], roseType: 'area',
            data: pieData2,
            avoidLabelOverlap: false,
            // 全部扁平结构（不包 normal）：echarts 4/5 都认；数据项级 labelLine 覆盖 series 级
            label: { show: true, formatter: function(p) { return '{name|' + p.name + '} {value|' + p.value + '}'; }, rich: { name: { color: '#ffffff', fontSize: 10 }, value: { color: '#ffffff', fontSize: 16, fontWeight: 'bold' } } },
            labelLine: { length: 6, length2: 10, lineStyle: { width: 1 } },
            itemStyle: { shadowBlur: 30, shadowColor: 'rgba(0, 0, 0, 0.4)' }
        }]
    });
    // 点击扇区 → 按项目类型筛选地图图钉（再点同一项取消）
    myChart.on('click', function(params) {
        if (params.componentType !== 'series') return;
        _typeFilter = (_typeFilter === params.name) ? null : params.name;
        if (window.yantaiMapChart && window.yantaiMapChart.setChartFilter) {
            window.yantaiMapChart.setChartFilter('type', _typeFilter);
        }
    });
}

// ====== Echart6: 项目阶段分布 (横向柱状图：施工中红橙高亮) ======
function initEchart6Alert() {
    var dom = document.getElementById('echart6');
    if (!dom) return;
    // 下钻：该区县阶段；非下钻：按当前周期过滤 project_list 后统计（stage 已归档为 5 类）
    var pieData = _drillDistrict ? buildTypeStage(_drillDistrict).stage_pie : buildPeriodPie('stage');
    if (pieData.length === 0) {
        if (chartInstances.echart6) { chartInstances.echart6.dispose(); chartInstances.echart6 = null; }
        dom.innerHTML = '<div style="height:100%;display:flex;align-items:center;justify-content:center;color:rgba(255,255,255,.5);font-size:13px;">该周期暂无项目</div>';
        return;
    }
    if (chartInstances.echart6) { chartInstances.echart6.dispose(); chartInstances.echart6 = null; }

    // 阶段语义配色：规划=灰蓝，招标=黄，施工=红橙(进行中强调)，完工=绿
    var stageColor = {
        '规划阶段': '#7db7e8',
        '招标阶段': '#ffea00',
        '施工阶段': '#ff7a45',
        '已勘察完工': '#39d98a'
    };
    var stages = [], values = [], colors = [];
    for (var i = 0; i < pieData.length; i++) {
        stages.push(pieData[i].name);
        values.push(pieData[i].value);
        colors.push(stageColor[pieData[i].name] || '#37a2da');
    }

    var myChart = echarts.init(dom);
    chartInstances.echart6 = myChart;
    myChart.setOption({
        tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
        grid: { left: '5', top: '5', right: '30', bottom: '0', containLabel: true },
        xAxis: {
            type: 'value',
            axisLine: { show: false }, axisTick: { show: false },
            splitLine: { lineStyle: { color: 'rgba(255,255,255,.1)' } },
            axisLabel: { textStyle: { color: 'rgba(255,255,255,.5)', fontSize: 10 } }
        },
        yAxis: {
            type: 'category', data: stages.slice().reverse(),   // 施工在上，更醒目
            axisLine: { lineStyle: { color: 'rgba(255,255,255,.2)' } },
            axisTick: { show: false },
            axisLabel: { textStyle: { color: '#fff', fontSize: 11 } }
        },
        series: [{
            name: '项目数', type: 'bar', barWidth: 12,
            data: values.slice().reverse().map(function(v, i) {
                return { value: v, itemStyle: { color: colors[values.length - 1 - i], barBorderRadius: [0, 6, 6, 0] } };
            }),
            label: { normal: { show: true, position: 'right', formatter: '{c}', textStyle: { color: '#ffffff', fontSize: 12, fontWeight: 'bold' } } }
        }]
    });
    // 点击柱子 → 按项目阶段筛选地图图钉（再点同一项取消）
    myChart.on('click', function(params) {
        if (params.componentType !== 'series') return;
        _stageFilter = (_stageFilter === params.name) ? null : params.name;
        if (window.yantaiMapChart && window.yantaiMapChart.setChartFilter) {
            window.yantaiMapChart.setChartFilter('stage', _stageFilter);
        }
    });
}

// ====== 施工实时统计联动（干线/骨干汇聚/其他 已施工化）→ 点击切到 3D 施工图模式 ======
// ====== 施工/预警统计点击联动（模式感知）：施工图模式=已在该模式；柱状图/预警图=按红/黄过滤图钉 ======
function bindStatFilter() {
    var red = document.getElementById('statRed');
    var yellow = document.getElementById('statYellow');
    var districts = document.getElementById('statDistricts');
    function onClick(kind) {
        var m = window.yantaiMapChart;
        if (!m) return;
        if (m._mapMode === 'work') return;   // 施工图模式：统计为施工级别，点击无过滤
        if (kind === 'red') m.setPinFilter('red');
        else if (kind === 'yellow') m.setPinFilter('yellow');
        else m.setPinFilter(null);
    }
    if (red) red.addEventListener('click', function () { onClick('red'); });
    if (yellow) yellow.addEventListener('click', function () { onClick('yellow'); });
    if (districts) districts.addEventListener('click', function () { onClick(null); });
}


// 统一刷新全部周期相关视图（2D 返回全市 / 模式切换后调用）：
// 图表在隐藏容器渲染会变 0 尺寸，返回后必须重建；柱状图/图钉/统计按当前周期刷新
function refreshAllCharts() {
    try {
        if (chartInstances.echart2) { chartInstances.echart2.dispose(); chartInstances.echart2 = null; }
        initEchart2();
    } catch (e) { console.error('refresh echart2:', e); }
    try { initEchart3(); } catch (e) { console.error('refresh echart3:', e); }
    try { initEchart5(); } catch (e) { console.error('refresh echart5:', e); }
    try { initEchart6(); } catch (e) { console.error('refresh echart6:', e); }
    try { updateStatPanel(); } catch (e) { console.error('refresh stat:', e); }
    try {
        if (window.yantaiMapChart && window.yantaiMapChart.updateBars) {
            window.yantaiMapChart.updateBars(buildDistrictRanking(_mqPeriod));
        }
        if (window.yantaiMapChart && window.yantaiMapChart.setPinPeriod) {
            window.yantaiMapChart.setPinPeriod(_mqPeriod);
        }
    } catch (e) { console.error('refresh map:', e); }
}
window.refreshAllCharts = refreshAllCharts;

// ====== 统一初始化入口 ======
function initAllCharts() {
    // 本周/本月/今年 按钮 → 联动全部左右栏图表（区县预警数据 echart2 / 项目类型 echart5 / 项目阶段分布 echart6）
    var dateBtns = document.querySelectorAll('.mq-date');
    for (var di = 0; di < dateBtns.length; di++) {
        dateBtns[di].addEventListener('click', function() {
            var dd = this.getAttribute('data-d');
            if (!dd || dd === _mqPeriod) return;
            _mqPeriod = dd;
            for (var dj = 0; dj < dateBtns.length; dj++) dateBtns[dj].classList.remove('is-active');
            this.classList.add('is-active');
            try {
                if (chartInstances.echart2) { chartInstances.echart2.dispose(); chartInstances.echart2 = null; }
                initEchart2();
            } catch(e) { console.error('echart2 period:', e); }
            try { initEchart5(); } catch(e) { console.error('echart5 period:', e); }
            try { initEchart6(); } catch(e) { console.error('echart6 period:', e); }
            // 周期联动：时间趋势 + 预警实时统计 + 3D 图钉
            try { initEchart3(); } catch(e) { console.error('echart3 period:', e); }
            try { updateStatPanel(); } catch(e) { console.error('statPanel period:', e); }
            try {
                if (window.yantaiMapChart && window.yantaiMapChart.setPinPeriod) {
                    window.yantaiMapChart.setPinPeriod(_mqPeriod);
                }
            } catch(e) { console.error('pinPeriod:', e); }
            // 3D 柱状图：柱高/柱顶项目数随周期变化（下钻态跳过——保持区县下钻，图钉由 setPinPeriod 刷新）
            try {
                if (window.yantaiMapChart && window.yantaiMapChart.replaceBars
                    && !window.yantaiMapChart._districtMode) {
                    window.yantaiMapChart.updateBars(buildDistrictRanking(_mqPeriod));
                }
            } catch(e) { console.error('bars period:', e); }
            // 2D 地图：标记/列表按周期重建（与 3D 图钉一致）
            try {
                if (window.GaodeMap2D && window.GaodeMap2D.refreshMarkers) {
                    window.GaodeMap2D.refreshMarkers();
                }
            } catch(e) { console.error('2d period:', e); }
            // 施工图 2D：道路线/列表按周期重建（本周/本月/今年）
            try {
                if (window.WorkMap2D && window.WorkMap2D.refreshByPeriod) {
                    window.WorkMap2D.refreshByPeriod(_mqPeriod);
                }
            } catch(e) { console.error('work period:', e); }
            // 抓取日志（施工项目）按周期刷新
            try { initMarquee(); } catch(e) { console.error('marquee period:', e); }
        });
    }
    try { initEchart2(); } catch(e) { console.error('echart2:', e); }
    try { initEchart3(); } catch(e) { console.error('echart3:', e); }
    try { initMarquee(); } catch(e) { console.error('marquee:', e); }
    try { updateStatPanel(); } catch(e) { console.error('statPanel:', e); }
    try { initEchart5(); } catch(e) { console.error('echart5:', e); }
    try { initEchart6(); } catch(e) { console.error('echart6:', e); }
    try { if (typeof initMap === 'function') initMap(); } catch(e) { console.error('map:', e); }
    try { bindStatFilter(); } catch(e) { console.error('statFilter:', e); }
    // 初始化一致性：地图加载完成后，柱状图/图钉按默认周期（本周）生效。
    // 轮询不设上限（地图加载耗时不定，超时会导致初始"加载成本月/全量"）——
    // barGroup 就绪后必然应用，且 _mqPeriod 默认 'week'，保证初始就是本周
    function applyPeriodToMap() {
        try {
            if (window.yantaiMapChart && window.yantaiMapChart.updateBars &&
                window.yantaiMapChart.barGroup) {
                window.yantaiMapChart.updateBars(buildDistrictRanking(_mqPeriod));
                window.yantaiMapChart.setPinPeriod(_mqPeriod);
                return;
            }
        } catch (e) { console.error('period init:', e); }
        setTimeout(applyPeriodToMap, 1000);
    }
    setTimeout(applyPeriodToMap, 1500);
    // 底部托盘滑入
    try {
        var tray = document.querySelector('.bottom-tray');
        if (tray && typeof gsap !== 'undefined') {
            gsap.to('.bottom-tray', { y: 0, opacity: 1, duration: 1.5, ease: 'power4.out', delay: 0.8 });
        }
    } catch(e) {}
}

// ====== 全局 resize ======
window.addEventListener('resize', function() {
    for (var key in chartInstances) {
        if (chartInstances[key]) { chartInstances[key].resize(); }
    }
    if (window.yantaiMapChart) { window.yantaiMapChart.resize(); }
});

// ====== 左栏面板模式路由：柱状图/预警图 = 预警数据（原版）；施工图模式 = 施工数据 ======
function leftPanelMode() {
    var m = window.yantaiMapChart;
    return (m && m._mapMode === 'work') ? 'work' : 'alert';
}
function initEchart2() {
    if (leftPanelMode() === 'work') { try { initWorkEchart2(); } catch (e) { console.error('work e2:', e); } }
    else { try { initEchart2Alert(); } catch (e) { console.error('alert e2:', e); } }
}
function initEchart3() {
    if (leftPanelMode() === 'work') { try { initWorkEchart3(); } catch (e) { console.error('work e3:', e); } }
    else { try { initEchart3Alert(); } catch (e) { console.error('alert e3:', e); } }
}
function updateStatPanel() {
    if (leftPanelMode() === 'work') { try { updateWorkStatPanel(); } catch (e) { console.error('work stat:', e); } }
    else { try { updateStatPanelAlert(); } catch (e) { console.error('alert stat:', e); } }
}
// 左栏标题/统计标签按模式切换文本（施工图=施工语义；柱状图/预警图=预警语义）
function applyLeftPanelText(mode) {
    var work = mode === 'work';
    var t1 = document.getElementById('titStat');
    var t2 = document.getElementById('titDist');
    var t3 = document.getElementById('titTrend');
    var t4 = document.getElementById('titType');
    var t5 = document.getElementById('titStage');
    var t6 = document.getElementById('titLog');
    var s1 = document.getElementById('spanRed');
    var s2 = document.getElementById('spanYellow');
    var s3 = document.getElementById('spanGreen');
    var elY = document.getElementById('statYellow');
    if (t1) t1.textContent = work ? '施工实时统计' : '预警实时统计';
    if (t2) t2.textContent = work ? '区县施工数据' : '区县预警数据';
    if (t3) t3.textContent = work ? '施工交底趋势' : '预警时间趋势';
    if (t4) t4.textContent = work ? '影响光缆条数' : '项目类型';
    if (t5) t5.textContent = work ? '施工阶段分布' : '项目阶段分布';
    // 日志标题带"实时监控中"子元素 → 用 innerHTML 保留
    if (t6) t6.innerHTML = (work ? '施工日志' : '抓取日志') +
      '<span class="tit-live"><span class="live-dot"></span>实时监控中</span>';
    if (s1) s1.textContent = work ? '干线' : '红色预警';
    if (s2) s2.textContent = work ? '骨干汇聚' : '黄色预警';
    if (s3) s3.textContent = work ? '其他' : '项目总数';
    if (elY) elY.style.color = work ? '#ff8a3d' : '#ffcc00';   // 骨干橙 / 预警黄
}
// 3D 模式切换（底部按钮）→ 左栏图表/统计/文本按模式刷新（three-map setMapMode 调用）
window.onMapModeChange = function (mode) {
    try { applyLeftPanelText(mode); } catch (e) { console.error('mode text:', e); }
    try { initEchart2(); } catch (e) { console.error('mode e2:', e); }
    try { initEchart3(); } catch (e) { console.error('mode e3:', e); }
    try { updateStatPanel(); } catch (e) { console.error('mode stat:', e); }
    try { initEchart5(); } catch (e) { console.error('mode e5:', e); }
    try { initEchart6(); } catch (e) { console.error('mode e6:', e); }
    try { initMarquee(); } catch (e) { console.error('mode marquee:', e); }   // 日志按模式切换（抓取/施工）
};
window.refreshModeCharts = function () { if (window.onMapModeChange) window.onMapModeChange(); };

// ====== 预警版（柱状图/预警图模式用；HEAD 原版） ======

// ====== 预警版（柱状图/预警图模式使用；恢复自 HEAD 原版） ======
// ====== Echart2: 区县预警排名 (红黄堆叠柱：红段=红色预警，黄段=黄色预警) ======
function initEchart2Alert() {
    var dom = document.getElementById('echart2');
    if (!dom) return;
    var d = getData();
    // 按 本周/本月/今年 过滤 project_list 后统计各区县红/黄（数据源 = 数据库 publish_date）
    var pl = filterByPeriod(d.project_list || [], _mqPeriod);
    var distMap = {};
    for (var i = 0; i < pl.length; i++) {
        var p = pl[i];
        if (!p || !p.district) continue;
        var k = statDistrict(p.district);   // 统计口径：开发区计入福山区
        if (!distMap[k]) distMap[k] = { red: 0, yellow: 0 };
        if (p.warning === '红色预警') distMap[k].red++;
        else if (p.warning === '黄色预警') distMap[k].yellow++;
    }
    var ranking = [];
    for (var n in distMap) ranking.push({ name: n, value: distMap[n].red + distMap[n].yellow });
    ranking.sort(function(a, b) { return b.value - a.value; });
    if (ranking.length === 0) {
        dom.innerHTML = '<div style="height:100%;display:flex;align-items:center;justify-content:center;color:rgba(255,255,255,.5);font-size:13px;">该周期暂无预警数据</div>';
        if (chartInstances.echart2) { chartInstances.echart2.dispose(); chartInstances.echart2 = null; }
        return;
    }
    var names = [], redData = [], yellowData = [];
    for (var j = 0; j < ranking.length; j++) {
        names.push(ranking[j].name);
        redData.push(distMap[ranking[j].name].red);
        yellowData.push(distMap[ranking[j].name].yellow);
    }

    var myChart = echarts.init(dom);
    chartInstances.echart2 = myChart;
    // 柱顶数字：按图例选中状态显示 总数(红+黄)/红数/黄数（点图例时联动）
    // 注：不能用 myChart.getOption()（setOption 内部同步调用 formatter 时 option 未就绪 → 白屏坑），
    // 用 legendselectchanged 事件参数缓存选中状态
    var _legendSel = null;   // null = 默认全选
    function barTopLabel() {
        var showRed = !_legendSel || _legendSel['红色预警'] !== false;
        var showYellow = !_legendSel || _legendSel['黄色预警'] !== false;
        return function(pp) {
            var r = redData[pp.dataIndex] || 0, y = yellowData[pp.dataIndex] || 0;
            if (showRed && showYellow) return (r + y) > 0 ? (r + y) : '';
            if (showRed) return r > 0 ? r : '';
            if (showYellow) return y > 0 ? y : '';
            return '';
        };
    }
    // 红段数字：仅「独显红」（黄段隐藏）时显示红数 → 黄段隐藏导致黄段 label 消失，由红段 label 补上
    function redTopLabel() {
        var showRed = !_legendSel || _legendSel['红色预警'] !== false;
        var showYellow = !_legendSel || _legendSel['黄色预警'] !== false;
        return function(pp) {
            if (!showRed || showYellow) return '';
            var r = redData[pp.dataIndex] || 0;
            return r > 0 ? r : '';
        };
    }
    // 图例点击 = echarts 自带 toggle（用户确认自带行为即可）；事件只缓存选中状态，
    // 供 label formatter 判断：全显=总数40、只黄=17(黄段柱顶)、只红=23(黄段隐藏后红段顶由 redTopLabel 补上)
    myChart.on('legendselectchanged', function(prm) {
        if (prm && prm.selected) _legendSel = prm.selected;
        myChart.setOption({
            series: [
                { label: { normal: { formatter: redTopLabel() } } },
                { label: { normal: { formatter: barTopLabel() } } }
            ]
        });
    });
    myChart.setOption({
        tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' },
            formatter: function(ps) {
                var s = '<div style="color:rgba(255,255,255,.85);font-size:12px;">' + ps[0].axisValue + '</div>';
                for (var k = 0; k < ps.length; k++) {
                    s += '<div style="font-size:11px;"><span style="display:inline-block;width:8px;height:8px;border-radius:2px;background:' + ps[k].color + ';margin-right:4px;"></span>' +
                        ps[k].seriesName + ' <b style="float:right;margin-left:10px;">' + ps[k].value + '</b></div>';
                }
                return s;
            } },
        legend: {
            bottom: 0, itemWidth: 10, itemHeight: 10, textStyle: { color: 'rgba(255,255,255,.6)', fontSize: 10 },
            data: ['红色预警', '黄色预警']
        },
        grid: { left: '0', top: '22', right: '0', bottom: E2_GRID_BOTTOM, containLabel: true },
        xAxis: {
            type: 'category', data: names,
            axisLine: { lineStyle: { color: 'rgba(255,255,255,.3)' } },
            axisTick: { show: false },
            axisLabel: { interval: 0, fontSize: 12, color: '#fff',
                rotate: E2_AXIS_ROTATE,   // 三周期统一旋转角度（可手动调整，见顶部 E2_AXIS_ROTATE）
                formatter: function(v) {
                    return v.replace('开发区(黄渤海新区)', '黄渤海').replace(/区$/, '').replace(/市$/, '');
                } }
        },
        yAxis: {
            type: 'value',
            interval: function(v) { return Math.max(1, Math.ceil(v.max / 6)); },   // 刻度间隔写：约6档，避免重叠
            max: function(v) { return Math.ceil(v.max); },
            axisLine: { show: false }, axisTick: { show: false },
            splitLine: { lineStyle: { color: 'rgba(255,255,255,.1)' } },
            axisLabel: { textStyle: { color: 'rgba(255,255,255,.85)', fontSize: 14 } }
        },
        series: [{
            name: '红色预警', type: 'bar', stack: 'total',
            data: redData, barWidth: 9,
            itemStyle: { normal: { color: '#ff385c' } },
            label: { normal: { show: true, position: 'top', distance: 1, formatter: redTopLabel(),
                textStyle: { color: '#ffffff', fontSize: 14, fontWeight: 'bold' } } }
        }, {
            name: '黄色预警', type: 'bar', stack: 'total',
            data: yellowData, barWidth: 9,
            itemStyle: { normal: { color: '#ffea00', barBorderRadius: [2, 2, 0, 0] } },
            label: { normal: { show: true, position: 'top', distance: 1, formatter: barTopLabel(),
                textStyle: { color: '#ffffff', fontSize: 14, fontWeight: 'bold' } } }
        }]
    });
}

// 周期起点（YYYY-MM-DD 字符串）：本周=7天前、本月=1号、今年=1月1日



// 时间趋势按周期动态计算：本周/本月按天、今年按月（数据源 project_list 的 publish_date）
function buildTimelineAlert(period) {
    var pl = filterByPeriod((getData().project_list || []), period);
    var now = new Date();
    var buckets = {}, order = [];
    var fmtKey;
    if (period === 'week') {
        fmtKey = function (d) { return d.slice(0, 10); };
        for (var i = 6; i >= 0; i--) {
            var t = new Date(now.getTime() - i * 86400000);
            var k = t.getFullYear() + '-' + pad2(t.getMonth() + 1) + '-' + pad2(t.getDate());
            buckets[k] = { total: 0, red: 0, yellow: 0 }; order.push(k);
        }
    } else if (period === 'month') {
        fmtKey = function (d) { return d.slice(0, 10); };
        var ym = now.getFullYear() + '-' + pad2(now.getMonth() + 1);
        for (var i = 1; i <= now.getDate(); i++) {
            var k = ym + '-' + pad2(i);
            buckets[k] = { total: 0, red: 0, yellow: 0 }; order.push(k);
        }
    } else {
        fmtKey = function (d) { return d.slice(0, 7); };
        var y = String(now.getFullYear());
        for (var m = 1; m <= now.getMonth() + 1; m++) {
            var k = y + '-' + pad2(m);
            buckets[k] = { total: 0, red: 0, yellow: 0 }; order.push(k);
        }
    }
    pl.forEach(function (p) {
        var dd = String(p.date || '');
        if (!dd) return;
        var key = fmtKey(dd);
        if (!buckets[key]) return;
        buckets[key].total++;
        if (p.warning === '红色预警') buckets[key].red++;
        else if (p.warning === '黄色预警') buckets[key].yellow++;
    });
    var out = { timeline: [], red_timeline: [], yellow_timeline: [] };
    order.forEach(function (k) {
        out.timeline.push({ date: k, value: buckets[k].total });
        out.red_timeline.push({ date: k, value: buckets[k].red });
        out.yellow_timeline.push({ date: k, value: buckets[k].yellow });
    });
    return out;
}

// ====== Echart3: 项目时间趋势 (三线: 总数+红色预警+黄色预警，随周期动态计算) ======
function initEchart3Alert() {
    var dom = document.getElementById('echart3');
    if (!dom) return;
    var d = getData();
    var tl = buildTimelineAlert(_mqPeriod);   // 按当前周期（本周/本月/今年）重算
    var timeline = tl.timeline;
    var redTL = tl.red_timeline;
    var yellowTL = tl.yellow_timeline;
    var dates = [];
    for (var i = 0; i < timeline.length; i++) { dates.push(timeline[i].date); }

    if (chartInstances.echart3) { chartInstances.echart3.dispose(); chartInstances.echart3 = null; }
    var myChart = echarts.init(dom);
    chartInstances.echart3 = myChart;
    myChart.setOption({
        tooltip: { trigger: 'axis' },
        legend: {
            bottom: 0, textStyle: { color: 'rgba(255,255,255,.6)', fontSize: 10 },
            data: [
                { name: '项目总数', textStyle: { color: '#37a2da' } },
                { name: '红色预警', textStyle: { color: '#ff4444' } },
                { name: '黄色预警', textStyle: { color: '#ffcc00' } }
            ]
        },
        grid: { left: '5', top: '10', right: '10', bottom: '25', containLabel: true },
        xAxis: {
            type: 'category', boundaryGap: false, data: dates,
            axisLabel: { textStyle: { color: 'rgba(255,255,255,.5)', fontSize: 10 } },
            axisLine: { lineStyle: { color: 'rgba(255,255,255,.2)' } }
        },
        yAxis: {
            type: 'value', axisTick: { show: false }, splitNumber: 3,
            axisLine: { show: false },
            axisLabel: { textStyle: { color: 'rgba(255,255,255,.5)', fontSize: 10 } },
            splitLine: { lineStyle: { color: 'rgba(255,255,255,.1)', type: 'dotted' } }
        },
        series: [{
            name: '项目总数', type: 'line', smooth: true, symbol: 'circle', symbolSize: 4,
            itemStyle: { color: '#37a2da' },
            lineStyle: { color: '#37a2da', width: 3 },
            areaStyle: { color: 'rgba(55,162,218,0.25)' },
            data: timeline.map(function(d) { return d.value; })
        }, {
            name: '红色预警', type: 'line', smooth: true, symbol: 'circle', symbolSize: 4,
            itemStyle: { color: '#ff4444' },
            lineStyle: { color: '#ff4444', width: 3 },
            areaStyle: { color: 'rgba(255,68,68,0.25)' },
            data: redTL.map(function(d) { return d.value; })
        }, {
            name: '黄色预警', type: 'line', smooth: true, symbol: 'circle', symbolSize: 4,
            itemStyle: { color: '#ffcc00' },
            lineStyle: { color: '#ffcc00', width: 3 },
            areaStyle: { color: 'rgba(255,204,0,0.25)' },
            data: yellowTL.map(function(d) { return d.value; })
        }]
    });
}

// 预警实时统计：红色/黄色预警数 + 项目总数（跟随下钻区县 + 当前周期）
// 数据源 = project_list（与区县预警/柱状图/饼图统一口径；map_points 缺坐标项目无法上图）
function updateStatPanelAlert() {
    var d = getData();
    var pts = d.project_list || [];
    var start = periodStartStr(_mqPeriod);
    var list = pts.filter(function (p) {
        if (!p) return false;
        // 统计口径：下钻福山区时开发区项目计入（地理在福山境内）
        if (_drillDistrict && !districtEq(_drillDistrict, statDistrict(p.district))) return false;
        if (start) {
            var dd = String(p.date || '');
            if (!dd || dd < start) return false;   // 无日期/早于周期起点 → 不计入
        }
        return true;
    });
    var red = 0;
    for (var i = 0; i < list.length; i++) {
        if (String(list[i].warning || '').indexOf('红色') >= 0) red++;
    }
    var elR = document.getElementById('statRed');
    var elY = document.getElementById('statYellow');
    var elD = document.getElementById('statDistricts');
    if (elR) elR.textContent = red;
    if (elY) elY.textContent = list.length - red;
    if (elD) elD.textContent = list.length;
}

function initEchart5Alert() {
    var dom = document.getElementById('echart5');
    if (!dom) return;
    // 下钻：该区县类型；非下钻：按当前周期（本周/本月/今年）过滤 project_list 后统计
    var pieData = _drillDistrict ? buildTypeStage(_drillDistrict).type_pie : buildPeriodPie('type');
    if (pieData.length === 0) {
        if (chartInstances.echart5) { chartInstances.echart5.dispose(); chartInstances.echart5 = null; }
        dom.innerHTML = '<div style="height:100%;display:flex;align-items:center;justify-content:center;color:rgba(255,255,255,.5);font-size:13px;">该周期暂无项目</div>';
        return;
    }
    if (chartInstances.echart5) { chartInstances.echart5.dispose(); chartInstances.echart5 = null; }
    var myChart = echarts.init(dom);
    chartInstances.echart5 = myChart;
    // 扇区级指示线长度：大扇区标签被推得远 → 线加长；小扇区往里收；确保所有扇区都有线
    // （今年/下钻全量数据扇区多易挤，统一收敛；海阳下钻的工业园区同样适用）
    var labelLineByType = {
        '工业厂房': { length: 10, length2: 12 },
        '工业园区': { length: 5, length2: 8 },
        '能源电力': { length: 6, length2: 10 },
        '住宅小区': { length: 3, length2: 5 },   // 恢复指示线（饼图已左移，标签不碰图例）
        '其他':     { length: 2, length2: 4 },
    };
    var pieData2 = pieData.map(function(d) {
        var ll = labelLineByType[d.name] || { length: 6, length2: 10 };
        // echarts 数据项级 labelLine 是扁平结构（不包 normal）；show:false 直接隐藏线
        return { name: d.name, value: d.value,
                 labelLine: { length: ll.length, length2: ll.length2, show: ll.show !== false } };
    });
    myChart.setOption({
        legend: { orient: 'vertical', itemWidth: 10, itemHeight: 10,
            textStyle: { color: 'rgba(255,255,255,.5)' }, top: 'center', right: 5,
            data: pieData.map(function(d) { return d.name; }) },
        color: ['#37a2da','#32c5e9','#9fe6b8','#ffdb5c','#ff9f7f','#fb7293','#e7bcf3','#8378ea','#1089E7'],
        tooltip: { trigger: 'item', formatter: "{b}: {c} ({d}%)" },
        series: [{
            // center 平衡：左侧留边界（不被卡片左缘裁剪）、右侧避图例
            type: 'pie', radius: [16, 62], center: ['31%', '50%'], roseType: 'area',
            data: pieData2,
            avoidLabelOverlap: false,
            // 全部扁平结构（不包 normal）：echarts 4/5 都认；数据项级 labelLine 覆盖 series 级
            label: { show: true, formatter: function(p) { return '{name|' + p.name + '} {value|' + p.value + '}'; }, rich: { name: { color: '#ffffff', fontSize: 10 }, value: { color: '#ffffff', fontSize: 16, fontWeight: 'bold' } } },
            labelLine: { length: 6, length2: 10, lineStyle: { width: 1 } },
            itemStyle: { shadowBlur: 30, shadowColor: 'rgba(0, 0, 0, 0.4)' }
        }]
    });
    // 点击扇区 → 按项目类型筛选地图图钉（再点同一项取消）
    myChart.on('click', function(params) {
        if (params.componentType !== 'series') return;
        _typeFilter = (_typeFilter === params.name) ? null : params.name;
        if (window.yantaiMapChart && window.yantaiMapChart.setChartFilter) {
            window.yantaiMapChart.setChartFilter('type', _typeFilter);
        }
    });
}

// ====== Echart6: 项目阶段分布 (横向柱状图：施工中红橙高亮) ======
function initEchart6Alert() {
    var dom = document.getElementById('echart6');
    if (!dom) return;
    // 下钻：该区县阶段；非下钻：按当前周期过滤 project_list 后统计（stage 已归档为 5 类）
    var pieData = _drillDistrict ? buildTypeStage(_drillDistrict).stage_pie : buildPeriodPie('stage');
    if (pieData.length === 0) {
        if (chartInstances.echart6) { chartInstances.echart6.dispose(); chartInstances.echart6 = null; }
        dom.innerHTML = '<div style="height:100%;display:flex;align-items:center;justify-content:center;color:rgba(255,255,255,.5);font-size:13px;">该周期暂无项目</div>';
        return;
    }
    if (chartInstances.echart6) { chartInstances.echart6.dispose(); chartInstances.echart6 = null; }

    // 阶段语义配色：规划=灰蓝，招标=黄，施工=红橙(进行中强调)，完工=绿
    var stageColor = {
        '规划阶段': '#7db7e8',
        '招标阶段': '#ffea00',
        '施工阶段': '#ff7a45',
        '已勘察完工': '#39d98a'
    };
    var stages = [], values = [], colors = [];
    for (var i = 0; i < pieData.length; i++) {
        stages.push(pieData[i].name);
        values.push(pieData[i].value);
        colors.push(stageColor[pieData[i].name] || '#37a2da');
    }

    var myChart = echarts.init(dom);
    chartInstances.echart6 = myChart;
    myChart.setOption({
        tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
        grid: { left: '5', top: '5', right: '30', bottom: '0', containLabel: true },
        xAxis: {
            type: 'value',
            axisLine: { show: false }, axisTick: { show: false },
            splitLine: { lineStyle: { color: 'rgba(255,255,255,.1)' } },
            axisLabel: { textStyle: { color: 'rgba(255,255,255,.5)', fontSize: 10 } }
        },
        yAxis: {
            type: 'category', data: stages.slice().reverse(),   // 施工在上，更醒目
            axisLine: { lineStyle: { color: 'rgba(255,255,255,.2)' } },
            axisTick: { show: false },
            axisLabel: { textStyle: { color: '#fff', fontSize: 11 } }
        },
        series: [{
            name: '项目数', type: 'bar', barWidth: 12,
            data: values.slice().reverse().map(function(v, i) {
                return { value: v, itemStyle: { color: colors[values.length - 1 - i], barBorderRadius: [0, 6, 6, 0] } };
            }),
            label: { normal: { show: true, position: 'right', formatter: '{c}', textStyle: { color: '#ffffff', fontSize: 12, fontWeight: 'bold' } } }
        }]
    });
    // 点击柱子 → 按项目阶段筛选地图图钉（再点同一项取消）
    myChart.on('click', function(params) {
        if (params.componentType !== 'series') return;
        _stageFilter = (_stageFilter === params.name) ? null : params.name;
        if (window.yantaiMapChart && window.yantaiMapChart.setChartFilter) {
            window.yantaiMapChart.setChartFilter('stage', _stageFilter);
        }
    });
}

// ====== 预警实时统计联动：红色/黄色预警 → 预警图按颜色过滤图钉 ======

// ====== Echart5 施工版：每个区县的影响光缆条数（柱状图，样式同"区县施工数据"） ======
function initWorkEchart5() {
    var dom = document.getElementById('echart5');
    if (!dom) return;
    var roads = workRoadsOf(_mqPeriod, _drillDistrict || null);
    var byD = {};
    WORK_DISTRICTS.forEach(function (d) { byD[d] = 0; });
    roads.forEach(function (r) {
        if (!r || !r.district || byD[r.district] === undefined) return;
        var n = parseFloat(r.cable_count);
        if (isFinite(n) && n > 0) byD[r.district] += n;
    });
    var names = WORK_DISTRICTS.slice();
    var vals = names.map(function (d) { return byD[d]; });
    var total = vals.reduce(function (a, b) { return a + b; }, 0);
    if (chartInstances.echart5) { chartInstances.echart5.dispose(); chartInstances.echart5 = null; }
    if (!total) {
        dom.innerHTML = '<div style="height:100%;display:flex;align-items:center;justify-content:center;color:rgba(255,255,255,.5);font-size:13px;">该周期暂无光缆数据</div>';
        return;
    }
    var myChart = echarts.init(dom);
    chartInstances.echart5 = myChart;
    myChart.setOption({
        tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' },
            formatter: function (ps) {
                return '<div style="color:#000;font-size:12px;font-weight:bold;">' + ps[0].axisValue +
                    '</div><div style="font-size:11px;color:#000;">影响光缆 <b style="float:right;margin-left:10px;">' + ps[0].value + ' 条</b></div>';
            } },
        grid: { left: '0', top: '18', right: '8', bottom: E2_GRID_BOTTOM, containLabel: true },
        xAxis: {
            type: 'category', data: names,
            axisLine: { lineStyle: { color: 'rgba(255,255,255,.3)' } },
            axisTick: { show: false },
            axisLabel: { interval: 0, fontSize: 11, color: '#fff', rotate: E2_AXIS_ROTATE,
                formatter: function (v) { return v.replace(/区$/, '').replace(/市$/, ''); } }
        },
        yAxis: {
            type: 'value',
            axisLine: { show: false }, axisTick: { show: false },
            splitLine: { lineStyle: { color: 'rgba(255,255,255,.1)' } },
            axisLabel: { textStyle: { color: 'rgba(255,255,255,.85)', fontSize: 12 } }
        },
        series: [{
            name: '影响光缆', type: 'bar', data: vals, barWidth: 9,
            itemStyle: { normal: { color: '#30dcff', barBorderRadius: [2, 2, 0, 0] } },
            label: { normal: { show: true, position: 'top', distance: 1,
                formatter: function (p) { return p.value > 0 ? p.value : ''; },
                textStyle: { color: '#ffffff', fontSize: 11 } } }
        }]
    });
}

// ====== Echart6 施工版：施工阶段分布（数据 = Excel 目前状态） ======
function initWorkEchart6() {
    var dom = document.getElementById('echart6');
    if (!dom) return;
    var roads = workRoadsOf(_mqPeriod, _drillDistrict || null);
    var sColor = { '施工中': '#22c55e', '暂停施工': '#ef4444', '已完工': '#9ca3af', '未开工': '#facc15' };
    var order = ['未开工', '已完工', '暂停施工', '施工中'];   // 底部→顶部：施工中置顶醒目
    var vals = {}, stages = [], values = [], colors = [];
    order.forEach(function (s) { vals[s] = 0; });
    roads.forEach(function (r) {
        var st = String(r.status || '').trim();
        if (vals[st] !== undefined) vals[st]++;
    });
    var total = 0;
    order.forEach(function (s) {
        total += vals[s];
        stages.push(s); values.push(vals[s]); colors.push(sColor[s]);
    });
    if (chartInstances.echart6) { chartInstances.echart6.dispose(); chartInstances.echart6 = null; }
    if (!total) {
        dom.innerHTML = '<div style="height:100%;display:flex;align-items:center;justify-content:center;color:rgba(255,255,255,.5);font-size:13px;">该周期暂无施工</div>';
        return;
    }
    var myChart = echarts.init(dom);
    chartInstances.echart6 = myChart;
    myChart.setOption({
        tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
        grid: { left: '5', top: '5', right: '30', bottom: '0', containLabel: true },
        xAxis: {
            type: 'value',
            axisLine: { show: false }, axisTick: { show: false },
            splitLine: { lineStyle: { color: 'rgba(255,255,255,.1)' } },
            axisLabel: { textStyle: { color: 'rgba(255,255,255,.5)', fontSize: 10 } }
        },
        yAxis: {
            type: 'category', data: stages,
            axisLine: { lineStyle: { color: 'rgba(255,255,255,.2)' } },
            axisTick: { show: false },
            axisLabel: { textStyle: { color: '#fff', fontSize: 11 } }
        },
        series: [{
            name: '道路数', type: 'bar', barWidth: 12,
            data: stages.map(function (s, i) {
                return { value: values[i], itemStyle: { color: colors[i], barBorderRadius: [0, 6, 6, 0] } };
            }),
            label: { normal: { show: true, position: 'right',
                formatter: '{c}', textStyle: { color: '#ffffff', fontSize: 12, fontWeight: 'bold' } } }
        }]
    });
}

// ====== echart5/6 模式分发器（柱状图/预警图=原类型/阶段；施工图=光缆条数/施工阶段） ======
function initEchart5() {
    if (leftPanelMode() === 'work') { try { initWorkEchart5(); } catch (e) { console.error('work e5:', e); } }
    else { try { initEchart5Alert(); } catch (e) { console.error('alert e5:', e); } }
}
function initEchart6() {
    if (leftPanelMode() === 'work') { try { initWorkEchart6(); } catch (e) { console.error('work e6:', e); } }
    else { try { initEchart6Alert(); } catch (e) { console.error('alert e6:', e); } }
}
