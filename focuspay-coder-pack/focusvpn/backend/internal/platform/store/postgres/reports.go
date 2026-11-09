package postgres

import (
	"context"
	"time"

	"focusvpn.example/focusvpn/backend/internal/platform/store"
)

// Reports returns the operator report sub-store.
func (s *Store) Reports() store.ReportStore { return s }

func (s *Store) AddNodeTraffic(ctx context.Context, nodeID string, day time.Time, rx, tx int64) error {
	_, err := s.pool.Exec(ctx,
		`INSERT INTO node_traffic_daily (node_id, day, rx_bytes, tx_bytes) VALUES ($1, $2::date, $3, $4)
		 ON CONFLICT (node_id, day) DO UPDATE
		 SET rx_bytes = node_traffic_daily.rx_bytes + EXCLUDED.rx_bytes,
		     tx_bytes = node_traffic_daily.tx_bytes + EXCLUDED.tx_bytes`,
		nodeID, day.UTC().Format("2006-01-02"), rx, tx)
	return err
}

func (s *Store) Summary(ctx context.Context, now time.Time) (store.ReportSummary, error) {
	var r store.ReportSummary
	err := s.pool.QueryRow(ctx, `SELECT
		(SELECT count(*) FROM subscriptions WHERE status IN ('trialing','active') AND ends_at > $1),
		(SELECT count(*) FROM devices WHERE status = 'active'),
		(SELECT count(*) FROM vpn_allocations WHERE status IN ('pending','active')),
		(SELECT count(*) FROM billing_events WHERE kind = 'paid' AND created_at >= $1 - interval '1 day'),
		(SELECT count(*) FROM billing_events WHERE kind = 'paid' AND created_at >= $1 - interval '7 days'),
		(SELECT count(*) FROM billing_events WHERE kind = 'paid' AND created_at >= $1 - interval '30 days'),
		(SELECT COALESCE(sum(days),0) FROM billing_events WHERE kind = 'paid' AND created_at >= $1 - interval '30 days'),
		(SELECT count(*) FROM billing_events WHERE kind = 'trial' AND created_at >= $1 - interval '30 days')`, now).
		Scan(&r.ActiveSubscriptions, &r.ActiveDevices, &r.LiveConnections,
			&r.Purchases1d, &r.Purchases7d, &r.Purchases30d, &r.PurchasedDays30d, &r.Trials30d)
	if err != nil {
		return r, err
	}
	today := now.UTC().Format("2006-01-02")
	rows, err := s.pool.Query(ctx, `SELECT n.id, n.name, n.country,
		COALESCE((SELECT e.state FROM vpn_endpoints e WHERE e.node_id = n.id
		          ORDER BY CASE e.state WHEN 'OFFLINE' THEN 0 WHEN 'DRAINING' THEN 1 WHEN 'DEGRADED' THEN 2 ELSE 3 END LIMIT 1), n.state),
		COALESCE((SELECT max(e.peer_count) FROM vpn_endpoints e WHERE e.node_id = n.id), 0),
		n.capacity,
		COALESCE((SELECT max(e.load) FROM vpn_endpoints e WHERE e.node_id = n.id), 0),
		n.last_heartbeat_at,
		COALESCE(n.status_reason, ''),
		COALESCE((SELECT rx_bytes FROM node_traffic_daily t WHERE t.node_id = n.id AND t.day = $1::date), 0),
		COALESCE((SELECT tx_bytes FROM node_traffic_daily t WHERE t.node_id = n.id AND t.day = $1::date), 0),
		COALESCE((SELECT sum(rx_bytes) FROM node_traffic_daily t WHERE t.node_id = n.id AND t.day > $1::date - 30), 0),
		COALESCE((SELECT sum(tx_bytes) FROM node_traffic_daily t WHERE t.node_id = n.id AND t.day > $1::date - 30), 0)
		FROM vpn_nodes n ORDER BY n.name`, today)
	if err != nil {
		return r, err
	}
	defer rows.Close()
	for rows.Next() {
		var n store.NodeReport
		if err := rows.Scan(&n.NodeID, &n.Name, &n.Country, &n.State, &n.Online, &n.Capacity, &n.Load,
			&n.LastHeartbeatAt, &n.StatusReason, &n.RxToday, &n.TxToday, &n.Rx30d, &n.Tx30d); err != nil {
			return r, err
		}
		r.Nodes = append(r.Nodes, n)
	}
	if err := rows.Err(); err != nil {
		return r, err
	}
	pauses, err := s.pool.Query(ctx,
		`SELECT p.allocation_id, p.ip_count, p.reason, p.until_at, COALESCE(p.node_id::text, ''),
		        COALESCE(n.name, ''), p.updated_at
		 FROM allocation_pauses p
		 LEFT JOIN vpn_nodes n ON n.id = p.node_id
		 WHERE p.until_at > $1
		 ORDER BY p.until_at`, now)
	if err != nil {
		return r, err
	}
	defer pauses.Close()
	for pauses.Next() {
		var p store.AllocationPause
		if err := pauses.Scan(&p.AllocationID, &p.IPCount, &p.Reason, &p.Until, &p.NodeID, &p.NodeName, &p.UpdatedAt); err != nil {
			return r, err
		}
		r.Pauses = append(r.Pauses, p)
	}
	return r, pauses.Err()
}
