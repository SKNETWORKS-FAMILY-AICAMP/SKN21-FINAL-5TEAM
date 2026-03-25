import type { DetailedHTMLProps, HTMLAttributes } from 'react';

type OrderCsWidgetElementProps = DetailedHTMLProps<HTMLAttributes<HTMLElement>, HTMLElement>;
type DaumPostcodeAddressData = {
  zonecode?: string;
  postcode?: string;
  address?: string;
};

declare module 'react' {
  namespace JSX {
    interface IntrinsicElements {
      'order-cs-widget': OrderCsWidgetElementProps;
    }
  }
}

declare module 'react/jsx-runtime' {
  namespace JSX {
    interface IntrinsicElements {
      'order-cs-widget': OrderCsWidgetElementProps;
    }
  }
}

declare global {
  interface Window {
    daum?: {
      Postcode: new (options: { oncomplete: (data: DaumPostcodeAddressData) => void }) => {
        open: () => void;
      };
    };
  }
}

export {};
