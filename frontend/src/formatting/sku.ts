import type { ListingCondition, SkuCategory, SkuSummary } from '../api/types';


const CATEGORY_LABELS: Record<SkuCategory, string> = {
  gpu: 'GPU',
  cpu: 'CPU',
  ram: 'RAM',
  mobo: 'Motherboard',
  monitor: 'Monitor',
  peripheral: 'Peripheral',
};

const CONDITION_LABELS: Record<ListingCondition, string> = {
  new: 'New',
  like_new: 'Like new',
  used: 'Used',
  for_parts: 'For parts',
};

export function skuDisplayName(sku: Pick<SkuSummary, 'brand' | 'model' | 'variant'>): string {
  return [sku.brand, sku.model, sku.variant]
    .map((part) => part.trim())
    .filter(Boolean)
    .join(' ');
}

export function categoryLabel(category: SkuCategory): string {
  return CATEGORY_LABELS[category] ?? category;
}

export function conditionLabel(condition: ListingCondition | null): string {
  if (condition === null) {
    return 'Unknown condition';
  }
  return CONDITION_LABELS[condition] ?? condition;
}
