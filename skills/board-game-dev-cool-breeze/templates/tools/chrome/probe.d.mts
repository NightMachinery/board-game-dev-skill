export interface PageProbe {
  iw: number; ih: number; sw: number; sh: number; hscroll: boolean; vscroll: boolean;
  viewportWidth: number; viewportHeight: number;
  domNodes: number; overflow: { el: string; left: number; right: number; width: number }[];
  viewportOutside: { el: string; left: number; right: number; top: number; bottom: number; width: number }[];
  covered: { el: string; by: string | null }[];
  tap: { count: number; smallest: { el: string; w: number; h: number; min: number } | null; under24: number; under44: number };
}
export function probePage(): PageProbe;
