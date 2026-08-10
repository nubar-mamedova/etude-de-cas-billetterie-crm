-- =====================================================================
-- LÜMA · Tournée ORBITE 2026-27 — requêtes d'analyse
-- Schéma : shows(show_id, city, venue, capacity, show_date, onsale_date, base_price)
--          orders(order_id, buyer_id, show_id, order_date, channel, tier,
--                 qty, unit_price, fee_per_ticket, gross, tour)
--          buyers(buyer_id, first_seen, source, dept, opt_in_email,
--                 opt_in_push, contactable)
-- =====================================================================

-- 1 ─ Rythme de vente : remplissage réel vs. courbe de référence de la tournée
--     Le remplissage brut ne veut rien dire tant qu'on ne le rapporte pas
--     au nombre de jours écoulés depuis la mise en vente.
WITH cumul AS (
  SELECT o.show_id,
         (o.order_date - s.onsale_date)                       AS jour,
         SUM(SUM(o.qty)) OVER (PARTITION BY o.show_id
                               ORDER BY (o.order_date - s.onsale_date)) AS cumule,
         s.capacity
  FROM   orders o JOIN shows s USING (show_id)
  WHERE  o.tour = 'ORBITE 2026-27'
  GROUP  BY o.show_id, jour, s.capacity
),
reference AS (                       -- médiane de la tournée à chaque jour J+n
  SELECT jour,
         PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY cumule::numeric / capacity) AS taux_ref
  FROM   cumul GROUP BY jour
),
etat AS (
  SELECT s.show_id, s.city, s.venue, s.capacity,
         SUM(o.qty)                                           AS vendus,
         (DATE '2026-08-04' - s.onsale_date)                   AS jours_en_vente,
         (s.show_date - DATE '2026-08-04')                     AS jours_avant_concert
  FROM   shows s JOIN orders o USING (show_id)
  WHERE  o.tour = 'ORBITE 2026-27'
  GROUP  BY s.show_id, s.city, s.venue, s.capacity, s.onsale_date, s.show_date
)
SELECT e.city, e.venue, e.capacity, e.vendus,
       ROUND(100.0 * e.vendus / e.capacity, 1)          AS taux_remplissage,
       ROUND(e.vendus / (r.taux_ref * e.capacity), 2)   AS indice_rythme,   -- < 0,85 = en retard
       e.jours_avant_concert
FROM   etat e JOIN reference r ON r.jour = e.jours_en_vente
ORDER  BY indice_rythme ASC;

-- 2 ─ Mix canal et fuite de données : combien d'acheteurs sont réellement joignables ?
--     Les revendeurs rendent le chiffre d'affaires, pas l'identité du fan.
SELECT o.channel,
       SUM(o.qty)                                                   AS billets,
       ROUND(100.0 * SUM(o.qty) / SUM(SUM(o.qty)) OVER (), 1)       AS part_pct,
       ROUND(SUM(o.gross)::numeric, 0)                              AS ca_billetterie,
       ROUND(SUM(o.fee_per_ticket * o.qty)::numeric, 0)             AS frais_payes_par_le_fan,
       COUNT(DISTINCT o.buyer_id)                                   AS acheteurs,
       COUNT(DISTINCT o.buyer_id) FILTER (WHERE b.contactable)      AS acheteurs_joignables
FROM   orders o JOIN buyers b USING (buyer_id)
WHERE  o.tour = 'ORBITE 2026-27'
GROUP  BY o.channel
ORDER  BY billets DESC;

-- 3 ─ Scores RFM (base de la segmentation)
--     F et M portent sur l'historique complet, 2024 inclus — sinon F vaut 1 partout
--     et la segmentation n'est qu'un habillage.
WITH base AS (
  SELECT buyer_id,
         DATE '2026-08-04' - MAX(order_date) AS recence,
         COUNT(*)                            AS frequence,
         SUM(gross)                          AS montant
  FROM   orders GROUP BY buyer_id
)
SELECT buyer_id, recence, frequence, montant,
       NTILE(4) OVER (ORDER BY recence DESC) AS score_r,   -- récent = score élevé
       LEAST(frequence, 4)                   AS score_f,
       NTILE(4) OVER (ORDER BY montant ASC)  AS score_m
FROM   base;

-- 4 ─ Cible opérationnelle de la campagne de rattrapage :
--     fans joignables, dans la zone de chalandise d'une date en retard,
--     qui n'ont pas encore de billet pour cette date.
SELECT b.buyer_id, b.dept
FROM   buyers b
WHERE  b.contactable                                  -- opt-in + email détenu en propre
  AND  b.dept IN ('31','33','34','09','81','82')      -- zone Toulouse
  AND  NOT EXISTS (
        SELECT 1 FROM orders o
        WHERE o.buyer_id = b.buyer_id AND o.show_id = 'S05');

-- 5 ─ Cohorte dormante : venue en 2024, silencieuse depuis.
SELECT b.buyer_id, b.dept, SUM(o.gross) AS depense_2024
FROM   buyers b JOIN orders o USING (buyer_id)
WHERE  o.tour = 'PREMIER CERCLE 2024'
  AND  b.buyer_id NOT IN (SELECT buyer_id FROM orders WHERE tour = 'ORBITE 2026-27')
GROUP  BY b.buyer_id, b.dept
ORDER  BY depense_2024 DESC;
