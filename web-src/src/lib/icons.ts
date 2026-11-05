/** 场景图标：按 tag / 标题关键词自动挑，后端给了 icon 就优先用后端的。
 *  以前这些 SVG 路径散在 app.js 顶部的一个大对象里，加上下面这串
 *  正则分支，一共 45 行、没有任何类型约束 —— 打错一个 key 也不会报错，
 *  只会静默显示成默认的 spark 图标。 */

export const ICONS = {
  cake: '<path d="M4 20h16M5.5 20v-5.6a2.5 2.5 0 0 1 2.5-2.5h8a2.5 2.5 0 0 1 2.5 2.5V20M4 16c1.2 0 1.8-.9 3-.9s1.8.9 3 .9 1.8-.9 3-.9 1.8.9 3 .9 1.8-.9 3-.9 1.8.9 3 .9M8 11.9V9.4M12 11.9V8M16 11.9V9.4M8 6.2V5.4M12 5.8V5M16 6.2V5.4"/>',
  heart:
    '<path d="M12 20.4S4.6 16 4.6 10.9A4.1 4.1 0 0 1 12 8.2a4.1 4.1 0 0 1 7.4 2.7c0 5.1-7.4 9.5-7.4 9.5z"/>',
  exam: '<path d="M2.4 9.2 12 5l9.6 4.2L12 13.4z"/><path d="M6.2 11.2v4.6c0 1.7 2.6 3 5.8 3s5.8-1.3 5.8-3v-4.6M21.6 9.2v5.4"/>',
  ticket:
    '<path d="M3.2 9.4a2 2 0 0 0 0 3.8v2.2a2.2 2.2 0 0 0 2.2 2.2h13.2a2.2 2.2 0 0 0 2.2-2.2v-2.2a2 2 0 0 1 0-3.8V7.2A2.2 2.2 0 0 0 18.6 5H5.4a2.2 2.2 0 0 0-2.2 2.2z"/><path d="M14 5.2v13.4"/>',
  pin: '<path d="M12 21s7-6.3 7-11.2a7 7 0 1 0-14 0C5 14.7 12 21 12 21z"/><circle cx="12" cy="9.6" r="2.5"/>',
  lantern:
    '<path d="M9.2 3.2h5.6M8 7.2h8M6.2 10.4c0 4 1.8 6.6 5.8 8 4-1.4 5.8-4 5.8-8zM12 18.4v2.2M9 20.6h6M12 7.2v3.2"/>',
  spark:
    '<path d="m12 3 1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8zM18.6 15.6l.7 2 2 .7-2 .7-.7 2-.7-2-2-.7 2-.7z"/>',
  calendar:
    '<rect x="3.4" y="5" width="17.2" height="15.4" rx="2.4"/><path d="M3.4 10h17.2M8 3v4M16 3v4"/>',
  gift: '<rect x="4" y="9" width="16" height="11" rx="2"/><path d="M3 9h18v4H3zM12 9v11M12 9c-3.6 0-5.4-1.3-5.4-3.2S8 3 9.2 3.9 12 9 12 9zm0 0c3.6 0 5.4-1.3 5.4-3.2S16 3 14.8 3.9 12 9 12 9z"/>',
  star: '<path d="m12 3.4 2.6 5.3 5.9.9-4.3 4.1 1 5.8-5.2-2.7-5.2 2.7 1-5.8-4.3-4.1 5.9-.9z"/>',
  moon: '<path d="M20.2 14.6A8.6 8.6 0 0 1 9.4 3.8a8.6 8.6 0 1 0 10.8 10.8z"/>',
  clock:
    '<circle cx="12" cy="12.4" r="7.8"/><path d="M12 8.2v4.6l3.1 2M7.4 4.8 5.6 3M16.6 4.8 18.4 3M8.2 2.8h7.6"/>',
  car: '<path d="M4.2 16.5h15.6M5.6 16.5l1-4.6a2 2 0 0 1 2-1.6h6.8a2 2 0 0 1 2 1.6l1 4.6M6.6 16.5v2.1M17.4 16.5v2.1M7.2 13.4h9.6"/><circle cx="7.8" cy="16.5" r="1.1"/><circle cx="16.2" cy="16.5" r="1.1"/>',
  food: '<path d="M4 12h16a6 6 0 0 1-6 6h-4a6 6 0 0 1-6-6zM7.2 9.2c0-1.4 1-1.9 1-3.4M12 9.2c0-1.4 1-1.9 1-3.4M16.8 9.2c0-1.4 1-1.9 1-3.4M3 20.2h18"/>',
  music: '<path d="M9 17.4V6.2l9.2-2v11"/><ellipse cx="6.5" cy="17.8" rx="2.7" ry="2.3"/><ellipse cx="15.7" cy="15.6" rx="2.7" ry="2.3"/>',
  satellite:
    '<path d="M4.5 19.5 8 16M4.8 13.2a8.2 8.2 0 0 1 6-6M7.8 16.2a4.4 4.4 0 0 1 3.2-3.2M10.2 10.2l3.6-3.6 3.6 3.6-3.6 3.6zM14 6.4 17.6 2.8M16.6 9 21.2 6.4M14.4 13.8l3 3"/>',
  wave: '<path d="M3 15c2.2 0 2.2-6 4.5-6s2.2 6 4.5 6 2.2-6 4.5-6 2.2 6 4.5 6"/>',
  flame:
    '<path d="M12 21c3.7 0 6.4-2.5 6.4-6.1 0-4.6-4.1-6.4-3.3-11.9-3 .6-5.2 3.3-5.2 5.7 0 1.2.5 2.2 1.2 3.1-1 .1-2.6-1-2.6-3.4C6.1 10.2 5.6 12.4 5.6 15c0 3.6 2.7 6 6.4 6z"/>',
  report: '<path d="M4 4h16v16H4zM8 8h8M8 12h8M8 16h5"/>',
  globe:
    '<circle cx="12" cy="12" r="8.4"/><path d="M3.6 12h16.8M12 3.6c2.7 2.6 4.1 5.4 4.1 8.4s-1.4 5.8-4.1 8.4c-2.7-2.6-4.1-5.4-4.1-8.4s1.4-5.8 4.1-8.4z"/>',
  bolt: '<path d="M13.6 2.6 5.2 13.4h5.6l-1 8 8.4-10.8h-5.6z"/>',
} as const;

export type IconKey = keyof typeof ICONS;

/** 关键词 → 图标。顺序有意义：先匹配到的赢，所以更具体的规则要放前面。 */
const RULES: ReadonlyArray<readonly [RegExp, IconKey]> = [
  [/outage|power|kplc|停电|电力/, "bolt"],
  [/taxi|打车|yango|car/, "car"],
  [/food|点餐|外卖|foodpanda|restaurant/, "food"],
  [/boomplay|music|音乐|最近播放/, "music"],
  [/satellite|卫星|玩机/, "satellite"],
  [/cross|country|city|跨国|跨城|location|定位/, "globe"],
  [/alarm|clock|闹钟|起床|时间管理/, "clock"],
  [/birthday|生日|cake/, "cake"],
  [/anniversary|纪念/, "heart"],
  [/exam|考试/, "exam"],
  [/show|concert|观演|追星|演出/, "ticket"],
  [/festival|节日|春节|中秋|端午|国庆|圣诞|新年|冬至/, "lantern"],
  [/important|重要/, "pin"],
  [/gift|礼/, "gift"],
  [/weather|天气/, "wave"],
  [/night|夜/, "moon"],
];

/** 给场景挑一个图标 key：后端 icon 合法就用它，否则按关键词猜，兜底 spark。 */
export function iconKeyFor(scenario: { id?: string; tag?: string; title?: string; icon?: string }): IconKey {
  const given = scenario.icon;
  if (given && given in ICONS) return given as IconKey;
  const hay = `${scenario.id ?? ""} ${scenario.tag ?? ""} ${scenario.title ?? ""}`.toLowerCase();
  for (const [re, key] of RULES) {
    if (re.test(hay)) return key;
  }
  return "spark";
}

/** 直接产出可插入的 <svg> 外框；内层路径交给模板 v-html 渲染。 */
export function iconBody(scenario: { id?: string; tag?: string; title?: string; icon?: string }): string {
  return ICONS[iconKeyFor(scenario)];
}
