// 烟台区县地图 — Three.js 3D 版本（替换 ECharts-GL）
import { YantaiMap3D } from './three-map.js';

var threeMap = null;

function initMap() {
	var dom = document.getElementById('map');
	if (!dom) return;

	// 销毁旧实例
	if (threeMap) {
		threeMap.destroy();
		threeMap = null;
	}

	threeMap = new YantaiMap3D(dom);

	var data = window.DASHBOARD_DATA || {};
	var mapPoints = data.map_points || [];

	threeMap.load().then(function() {
		// 预警散点已停用（2026-08-19）：白色箭头 Sprite 在柱状图/热力图模式显示为白色三角，
		// 用户要求直接隐藏——任何模式不再创建散点；预警图模式用 3D 图钉替代
		// 如需恢复：去掉注释即可（addScatter 方法仍在 three-map.js 保留）
		/*
		for (var i = 0; i < mapPoints.length; i++) {
			var p = mapPoints[i];
			var lng = p.value[0];
			var lat = p.value[1];
			var priority = p.value[2] || 1;
			var color = p.category === 'red' ? 0xff4444 : 0xffcc00;
			threeMap.addScatter(lng, lat, priority, color, p.name, p);
		}
		// 测试预警散点（真实数据接入前，用于验证点击→卡片→查看街道）
		threeMap.addScatter(121.39, 37.52, 4, 0xff4444, '测试预警点', {
			name: '测试预警点（烟台市中心）',
			value: [121.39, 37.52, 4],
			district: '芝罘区',
			project_type: '测试项目',
			stage: '测试阶段',
			warning: '红色预警',
			category: 'red'
		});
		*/
	});
}

// 暴露到全局，供 js.js 调用
window.initMap = initMap;

// 如果 XHR 数据先到（DASHBOARD_DATA 已设置），自动触发地图初始化
if (window.DASHBOARD_DATA) {
	initMap();
}

// 兼容旧的 resize 引用
Object.defineProperty(window, 'yantaiMapChart', {
	get: function() { return threeMap; },
	configurable: true
});
