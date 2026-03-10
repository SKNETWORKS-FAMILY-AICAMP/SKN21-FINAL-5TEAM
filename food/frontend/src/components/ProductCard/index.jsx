import React from "react";

const ProductCard = ({ name, price }) => (
  <article>
    <h2>{name}</h2>
    <p>Price: ${price}</p>
  </article>
);

export default ProductCard;
