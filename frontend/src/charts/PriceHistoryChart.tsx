import { useId } from 'react';
import type { ReactNode } from 'react';
import {
  Area,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import type { TooltipContentProps } from 'recharts';

import type { ListingCondition, PricePoint } from '../api/types';
import { formatMoneyDecimal } from '../formatting/decimal';
import { conditionLabel } from '../formatting/sku';
import { formatDateOnly, formatManilaTimestamp } from '../formatting/time';
import { toChartPoint } from './priceHistory';
import type { PriceHistoryChartPoint } from './priceHistory';
import styles from './PriceHistoryChart.module.css';


// Cool, legible on the recessed dark plot face, and still distinguishable by
// dash pattern alone so the series never depend on colour.
const SERIES_STYLES: Record<ListingCondition, { color: string; dash?: string }> = {
  new: { color: '#4ecfb0' },
  like_new: { color: '#5aa8f7', dash: '7 3' },
  used: { color: '#a68bf5', dash: '3 3' },
  for_parts: { color: '#e0a544', dash: '10 3 2 3' },
};

const AXIS_TICK = { fill: '#7f8fa7', fontSize: 11 };
const GRID_STROKE = 'rgba(255, 255, 255, 0.07)';

function PriceHistoryTooltip({
  active,
  payload,
}: TooltipContentProps) {
  if (!active || !payload?.length) {
    return null;
  }

  const point = payload.find((entry) => entry.payload)?.payload as
    | PriceHistoryChartPoint
    | undefined;
  if (!point) {
    return null;
  }

  return (
    <div className={styles.tooltip}>
      <strong>{formatDateOnly(point.evidence.day)}</strong>
      <span>{conditionLabel(point.evidence.condition)}</span>
      <dl>
        <div><dt>Median</dt><dd>{formatMoneyDecimal(point.evidence.median)}</dd></div>
        <div><dt>p25</dt><dd>{formatMoneyDecimal(point.evidence.p25)}</dd></div>
        <div><dt>p75</dt><dd>{formatMoneyDecimal(point.evidence.p75)}</dd></div>
      </dl>
    </div>
  );
}

interface PriceHistoryChartProps {
  pricePoints: PricePoint[];
}

interface AuditEvidenceCellProps {
  field: keyof PricePoint;
  index: number;
  points: PricePoint[];
  children: ReactNode;
}

function AuditEvidenceCell({ field, index, points, children }: AuditEvidenceCellProps) {
  const value = points[index]?.[field];

  // Row spans keep repeated audit metadata associated with every covered evidence row.
  if (index > 0 && points[index - 1]?.[field] === value) {
    return null;
  }

  let rowSpan = 1;
  while (points[index + rowSpan]?.[field] === value) {
    rowSpan += 1;
  }

  return <td rowSpan={rowSpan}>{children}</td>;
}

export default function PriceHistoryChart({ pricePoints }: PriceHistoryChartProps) {
  const descriptionId = useId();
  const chartPoints = pricePoints.map(toChartPoint);
  const conditions = Array.from(new Set(pricePoints.map((point) => point.condition)));

  return (
    <section className={`pw-panel ${styles.section}`} aria-labelledby="price-history-heading">
      <div className={styles.sectionHeading}>
        <div>
          <p className={styles.eyebrow}>Presentation view</p>
          <h2 id="price-history-heading">Persisted price history</h2>
        </div>
        <p>Median with the persisted p25–p75 range</p>
      </div>

      <div
        className={styles.chart}
        role="img"
        aria-label="Price history chart"
        aria-describedby={descriptionId}
      >
        <p id={descriptionId} className="visuallyHidden">
          Presentation-only chart of server-provided medians and p25 to p75 ranges.
          The adjacent table is the authoritative price history evidence.
        </p>
        <ResponsiveContainer width="100%" height={360} minWidth={0}>
          <ComposedChart data={chartPoints} margin={{ top: 18, right: 18, bottom: 24, left: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke={GRID_STROKE} vertical={false} />
            <XAxis
              dataKey="day"
              tickFormatter={formatDateOnly}
              minTickGap={24}
              tick={AXIS_TICK}
              stroke="rgba(255, 255, 255, 0.14)"
            />
            <YAxis tick={false} width={18} stroke="rgba(255, 255, 255, 0.14)" />
            <Tooltip content={PriceHistoryTooltip} cursor={{ stroke: GRID_STROKE }} />
            <Legend verticalAlign="top" height={52} />
            {conditions.map((condition) => (
              <Area
                key={`${condition}-range`}
                type="linear"
                dataKey={(point: PriceHistoryChartPoint) => (
                  point.condition === condition ? point.range : undefined
                )}
                name={`${conditionLabel(condition)} p25–p75`}
                stroke="none"
                fill={SERIES_STYLES[condition].color}
                fillOpacity={0.14}
                connectNulls={false}
                isAnimationActive={false}
              />
            ))}
            {conditions.map((condition) => (
              <Line
                key={`${condition}-median`}
                type="linear"
                dataKey={(point: PriceHistoryChartPoint) => (
                  point.condition === condition ? point.median : undefined
                )}
                name={`${conditionLabel(condition)} median`}
                stroke={SERIES_STYLES[condition].color}
                strokeWidth={2.5}
                strokeDasharray={SERIES_STYLES[condition].dash}
                dot={{ r: 2.5, strokeWidth: 2, fill: '#0b0f15' }}
                activeDot={{ r: 5 }}
                connectNulls={false}
                isAnimationActive={false}
              />
            ))}
          </ComposedChart>
        </ResponsiveContainer>
      </div>

      <div className={styles.tableWrap}>
        <table aria-label="Persisted price history evidence">
          <caption>Persisted price history evidence</caption>
          <thead>
            <tr>
              <th scope="col">Day</th>
              <th scope="col">Condition</th>
              <th scope="col">Median</th>
              <th scope="col">p25</th>
              <th scope="col">p75</th>
              <th scope="col">Samples</th>
              <th scope="col">MAD</th>
              <th scope="col">Window start</th>
              <th scope="col">Window end</th>
              <th scope="col">Calculated</th>
              <th scope="col">Contract</th>
            </tr>
          </thead>
          <tbody>
            {pricePoints.map((point, index) => (
              <tr key={point.id}>
                <td>{formatDateOnly(point.day)}</td>
                <td>{conditionLabel(point.condition)}</td>
                <td>{formatMoneyDecimal(point.median)}</td>
                <td>{formatMoneyDecimal(point.p25)}</td>
                <td>{formatMoneyDecimal(point.p75)}</td>
                <td>{point.n_listings}</td>
                <AuditEvidenceCell field="mad" index={index} points={pricePoints}>
                  {formatMoneyDecimal(point.mad)}
                </AuditEvidenceCell>
                <AuditEvidenceCell field="window_start_day" index={index} points={pricePoints}>
                  {formatDateOnly(point.window_start_day)}
                </AuditEvidenceCell>
                <AuditEvidenceCell field="window_end_day" index={index} points={pricePoints}>
                  {formatDateOnly(point.window_end_day)}
                </AuditEvidenceCell>
                <AuditEvidenceCell field="calculated_at" index={index} points={pricePoints}>
                  {formatManilaTimestamp(point.calculated_at)}
                </AuditEvidenceCell>
                <AuditEvidenceCell
                  field="calculation_contract_version"
                  index={index}
                  points={pricePoints}
                >
                  {point.calculation_contract_version ?? 'Unavailable'}
                </AuditEvidenceCell>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
