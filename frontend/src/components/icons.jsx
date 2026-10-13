export const ITEMS = ['Ration', 'POL', 'Ammo', 'Medical'];
export const ITEM_LABEL = { Ration: 'Rations', POL: 'Fuel (POL)', Ammo: 'Ammunition', Medical: 'Medical' };

const P = {
  Ration: 'M4 18h16M6 18c0-4 2.5-7 6-7s6 3 6 7M12 11V7m-2 0h4',
  POL: 'M12 3s6 6.5 6 11a6 6 0 0 1-12 0c0-4.5 6-11 6-11z',
  Ammo: 'M9 21V10l3-6 3 6v11zM9 14h6',
  Medical: 'M10 4h4v6h6v4h-6v6h-4v-6H4v-4h6z',
  Road: 'M3 17h18M5 17l2-9h10l2 9M12 8v3m0 2v2',
  Air: 'M21 15l-8-3V6a1 1 0 0 0-2 0v6l-8 3v2l8-1.5V19l-2 1.5V22l3-1 3 1v-1.5L13 19v-3.5l8 1.5z',
  Mule: 'M4 16V9l3-2h6l4 3v6M7 16v4M15 16v4M4 12h13',
};
export const Icon = ({ name, size = 18 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={P[name] || P.Road} /></svg>
);
