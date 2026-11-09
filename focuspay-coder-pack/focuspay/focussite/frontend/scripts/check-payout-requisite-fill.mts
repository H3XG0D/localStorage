import { fillTank } from "../src/panel/lib/payoutRequisiteFill.ts";

function eq(actual: number, expected: number, label: string) {
  if (Math.abs(actual - expected) > 0.009) {
    throw new Error(`${label}: got ${actual}, expected ${expected}`);
  }
}

const shot = fillTank({
  amountRub: 7000,
  paidRub: 0,
  allocations: [
    { status: "RESERVED", amount_rub: 4315.6 },
    { status: "CANCELED", amount_rub: 2586 },
  ],
});
eq(shot.reserved, 4315.6, "screenshot reserved");
eq(shot.free, 2684.4, "screenshot free");

const api = fillTank({ amountRub: 7000, paidRub: 1000, reservedRub: 2000, freeRub: 4000 });
eq(api.reserved, 2000, "api reserved");
eq(api.free, 4000, "api free");

const team = fillTank({ amountRub: 7000, paidRub: 0, reservedRub: 4315.6, allocations: [] });
eq(team.reserved, 4315.6, "team reserved from api");
eq(team.free, 2684.4, "team free from api");

console.log("ok");
