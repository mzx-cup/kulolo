import { state } from "@/stores/core";
import type { ScenarioParam } from "@/types/api";

/** 参数表单的状态与提交体构造。
 *
 *  约定：state.params 里 time 型存两个字段 `<key>.h` / `<key>.m`，
 *  其余类型存字符串。提交给后端时再按后端认的形状拼：
 *  time 型要拆成 hour / minute（后端 _allowed_params 就是这么拆的）。 */

/** 场景切换时把参数重置成默认值 */
export function resetParams(): void {
  const next: Record<string, string> = {};
  for (const p of state.selected?.params ?? []) {
    if (p.type === "time") {
      next[`${p.key}.h`] = String(p.h ?? 9);
      next[`${p.key}.m`] = String(p.m ?? 30);
    } else if (p.type === "number") {
      next[p.key] = String(p.value ?? "");
    } else if (p.type === "select") {
      next[p.key] = String(p.value ?? p.options?.[0]?.v ?? "");
    } else {
      next[p.key] = String(p.value ?? "");
    }
  }
  state.params = next;
}

/** 单个字段变化 */
export function setParam(key: string, value: string): void {
  state.params[key] = value;
}

/** 拼提交体。空值不提交（后端会用自己的默认值），number 型转成数字。 */
export function collectParams(): Record<string, string | number> {
  const body: Record<string, string | number> = {};
  const params: ScenarioParam[] = state.selected?.params ?? [];
  for (const p of params) {
    if (p.type === "time") {
      const h = state.params[`${p.key}.h`];
      const m = state.params[`${p.key}.m`];
      if (h !== undefined) body.hour = Number(h);
      if (m !== undefined) body.minute = Number(m);
    } else {
      const raw = (state.params[p.key] ?? "").trim();
      if (raw !== "") body[p.key] = p.type === "number" ? Number(raw) : raw;
    }
  }
  return body;
}

/** 规格行取值：带 `from` 的实时读参数值，否则用静态 `v`。
 *
 *  为什么需要 `sc` 参数：舞台会同时渲染中央卡和左右侧卡，**非选中卡**的
 *  参数不在 `state.params` 里（那是选中卡的编辑态）。所以要按「这张卡自己的
 *  参数定义 + 它自己的默认值」来算，而不是一律读 state.selected。
 *
 *  以前舞台直接写 `sp.v ?? "—"`，导致所有 `from` 型规格行（等待时间、目标
 *  日期这种跟着参数变的）都显示成一个下划线 —— 就是这个原因。
 */
export function specValue(
  sp: { k: string; v?: string | number; from?: string; prefix?: string; suffix?: string },
  sc?: { id?: string; params?: ScenarioParam[] },
): string {
  if (sp.from) {
    const key = sp.from;
    const param = sc?.params?.find((p) => p.key === key);
    /* 只有「这张卡就是当前选中卡」时，才用编辑中的 state.params；
       其它卡一律用它自己的默认值，避免把选中卡的参数张冠李戴。 */
    const isSelected = !sc?.id || sc.id === state.selected?.id;
    let raw: string | undefined;
    if (param?.type === "time") {
      const h = (isSelected ? state.params[`${key}.h`] : undefined)
        ?? String(param.h ?? 9);
      const m = (isSelected ? state.params[`${key}.m`] : undefined)
        ?? String(param.m ?? 30);
      raw = `${h.padStart(2, "0")}:${m.padStart(2, "0")}`;
    } else if (isSelected) {
      raw = state.params[key];
    }
    if (raw === undefined && param) raw = String(param.value ?? "");
    return `${sp.prefix ?? ""}${raw ?? ""}${sp.suffix ?? ""}`;
  }
  return sp.v === undefined || sp.v === null ? "" : String(sp.v);
}
