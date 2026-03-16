import React from "react";

const CartItem = ({ product, quantity }) => (
  <div>
    <strong>{product}</strong>
    <p>수량: {quantity}</p>
  </div>
);

export default CartItem;
