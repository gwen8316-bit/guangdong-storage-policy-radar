export const base = import.meta.env.BASE_URL.replace(/\/$/, '');
export const link = (path = '') => `${base}/${path.replace(/^\//, '')}`;
