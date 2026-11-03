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

/** Hero 面板右侧那排规格：带 from 的实时读参数框里的值。 */
export function specValue(sp: { k: string; v?: string | number; from?: string; prefix?: string; suffix?: string }): string {
  if (sp.from) {
    const key = sp.from;
    const param = state.selected?.params?.find((p) => p.key === key);
    let raw: string | undefined;
    if (param?.type === "time") {
      const h = state.params[`${key}.h`] ?? String(param.h ?? 9);
      const m = state.params[`${key}.m`] ?? String(param.m ?? 30);
      raw = `${h.padStart(2, "0")}:${m.padStart(2, "0")}`;
    } else {
      raw = state.params[key];
    }
    return `${sp.prefix ?? ""}${raw ?? ""}${sp.suffix ?? ""}`;
  }
  return sp.v === undefined || sp.v === null ? "" : String(sp.v);
}
