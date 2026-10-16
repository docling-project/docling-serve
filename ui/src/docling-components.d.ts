import type { DetailedHTMLProps, HTMLAttributes } from "react";

type DoclingElementProps = DetailedHTMLProps<HTMLAttributes<HTMLElement>, HTMLElement> & {
  /** A DoclingDocument object, or the URL of its JSON. */
  src?: unknown;
  /** Item reference paths to show, e.g. "#/tables, #/pictures". */
  items?: string;
  pagenumbers?: boolean;
  backdrop?: boolean;
  trim?: "pages";
};

// Web components from @docling/docling-components, used in JSX.
declare module "react" {
  namespace JSX {
    interface IntrinsicElements {
      "docling-img": DoclingElementProps;
      "docling-table": DoclingElementProps;
      "docling-tooltip": DetailedHTMLProps<HTMLAttributes<HTMLElement>, HTMLElement>;
      "docling-overlay": DetailedHTMLProps<HTMLAttributes<HTMLElement>, HTMLElement>;
    }
  }
}
