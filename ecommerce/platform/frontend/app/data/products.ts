// ecommerce/platform/frontend/app/data/products.ts

export type Product = {
  id: number;
  gender: string;
  masterCategory: string;
  subCategory: string;
  articleType: string;
  baseColour: string;
  season: string;
  year: number;
  usage: string;
  productDisplayName: string;

  // ✅ UI(사장님 트리)와 1:1로 붙일 키 (필수)
  uiCategory: string;     // 예: '상의'
  uiSubCategory: string;  // 예: '티셔츠'

  // ✅ 임시 가격(나중에 서버에서 교체)
  price?: number;
};

export const PRODUCTS: Product[] = [
  {
    id: 24050,
    gender: 'Men',
    masterCategory: 'Apparel',
    subCategory: 'Topwear',
    articleType: 'Tshirts',
    baseColour: 'Blue',
    season: 'Fall',
    year: 2011,
    usage: 'Casual',
    productDisplayName: 'Locomotive Men Printed Blue T-shirt',

    uiCategory: '상의',
    uiSubCategory: '티셔츠',
    price: 59000,
  },
  {
    id: 13967,
    gender: 'Men',
    masterCategory: 'Apparel',
    subCategory: 'Topwear',
    articleType: 'Tshirts',
    baseColour: 'Red',
    season: 'Fall',
    year: 2011,
    usage: 'Casual',
    productDisplayName: 'Ed Hardy Men Printed Red Tshirts',

    uiCategory: '상의',
    uiSubCategory: '티셔츠',
    price: 69000,
  },

  // ✅ 예시: 하의-반바지 (이미지 파일이 있는 id로 넣으셔야 함)
  {
    id: 1550,
    gender: 'Men',
    masterCategory: 'Apparel',
    subCategory: 'Bottomwear',
    articleType: 'Shorts',
    baseColour: 'Black',
    season: 'Summer',
    year: 2012,
    usage: 'Casual',
    productDisplayName: 'Basic Shorts',

    uiCategory: '하의',
    uiSubCategory: '반바지',
    price: 39000,
  },
];
