package postgres

import (
	"context"

	"focusvpn.example/focusvpn/backend/internal/platform/id"
	"focusvpn.example/focusvpn/backend/internal/platform/store"
)

func (s *Store) UpsertVLESSNode(ctx context.Context, n store.VLESSNode) (string, string, error) {
	if n.Capacity <= 0 {
		n.Capacity = 500
	}
	if n.Region == "" {
		n.Region = "unspecified"
	}
	if len(n.Xray) == 0 {
		n.Xray = []byte(`{}`)
	}
	tx, err := s.pool.Begin(ctx)
	if err != nil {
		return "", "", err
	}
	defer tx.Rollback(ctx) //nolint:errcheck

	if n.Subnet == "" {
		rows, err := tx.Query(ctx, `SELECT host(subnet)||'/'||masklen(subnet) FROM vpn_endpoints`)
		if err != nil {
			return "", "", err
		}
		var used []string
		for rows.Next() {
			var c string
			if err := rows.Scan(&c); err != nil {
				rows.Close()
				return "", "", err
			}
			used = append(used, c)
		}
		rows.Close()
		if err := rows.Err(); err != nil {
			return "", "", err
		}
		n.Subnet = store.AssignSubnet(used, "")
	}

	var nodeID string
	if err := tx.QueryRow(ctx, `INSERT INTO vpn_nodes (id, name, country, region, state, capacity, hostname)
		VALUES ($1,$2,$3,$4,'OFFLINE',$5,$6)
		ON CONFLICT (name) DO UPDATE SET
		  country = EXCLUDED.country, region = EXCLUDED.region, capacity = EXCLUDED.capacity,
		  hostname = EXCLUDED.hostname, updated_at = now()
		RETURNING id`, id.NewUUID(), n.Name, n.Country, n.Region, n.Capacity, n.Hostname).Scan(&nodeID); err != nil {
		return "", "", err
	}

	var endpointID string
	if err := tx.QueryRow(ctx, `INSERT INTO vpn_endpoints (id, node_id, protocol, port, state, subnet, xray)
		VALUES ($1,$2,'vless',443,'OFFLINE',$3::cidr,$4::jsonb)
		ON CONFLICT (node_id, protocol, port) DO UPDATE SET
		  xray = EXCLUDED.xray, updated_at = now()
		RETURNING id`, id.NewUUID(), nodeID, n.Subnet, n.Xray).Scan(&endpointID); err != nil {
		return "", "", err
	}
	if _, err := tx.Exec(ctx, `INSERT INTO node_state_versions (node_id, version) VALUES ($1, 0) ON CONFLICT DO NOTHING`, nodeID); err != nil {
		return "", "", err
	}
	if err := tx.Commit(ctx); err != nil {
		return "", "", err
	}
	return nodeID, endpointID, nil
}
