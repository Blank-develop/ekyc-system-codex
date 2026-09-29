/**
 * Lao display text for values that arrive from the API in English (challenge
 * prompts, decisions, statuses). The API keeps its English values and IDs; only
 * what the user sees is translated here. Unknown values fall back to the
 * original text so a new backend prompt never renders blank.
 */

import { L } from "./i18n";

type ChallengeLike = { id: string; prompt: string; instruction: string };

const CHALLENGE_TEXT: Record<string, { prompt: string; instruction: string }> = {
  // Active face liveness
  turn_left: { prompt: "ຫັນຊ້າຍ", instruction: "ຄ່ອຍໆຫັນຫົວໄປທາງຊ້າຍ." },
  turn_right: { prompt: "ຫັນຂວາ", instruction: "ຄ່ອຍໆຫັນຫົວໄປທາງຂວາ." },
  blink: { prompt: "ກະພິບຕາສອງເທື່ອ", instruction: "ກະພິບຕາສອງເທື່ອ ໂດຍໃຫ້ເຫັນໃບໜ້າຕະຫຼອດ." },
  open_mouth: { prompt: "ອ້າປາກ", instruction: "ອ້າປາກຈັກໜ່ອຍ ແລ້ວຫຸບປາກ." },
  // Hand gestures
  one: { prompt: "ຊູ 1 ນິ້ວ", instruction: "ຊູນິ້ວໜຶ່ງນິ້ວພາຍໃນວົງມົນ." },
  two: { prompt: "ຊູ 2 ນິ້ວ", instruction: "ຊູສອງນິ້ວພາຍໃນວົງມົນ." },
  three: { prompt: "ຊູ 3 ນິ້ວ", instruction: "ຊູສາມນິ້ວພາຍໃນວົງມົນ." },
  four: { prompt: "ຊູ 4 ນິ້ວ", instruction: "ຊູສີ່ນິ້ວພາຍໃນວົງມົນ." },
  five: { prompt: "ຊູ 5 ນິ້ວ", instruction: "ແບມືອອກພາຍໃນວົງມົນ." },
  point: { prompt: "ຊີ້ຂຶ້ນ", instruction: "ຊີ້ນິ້ວໜຶ່ງນິ້ວຂຶ້ນເທິງພາຍໃນວົງມົນ." },
  peace: { prompt: "ທ່າສັນຕິພາບ", instruction: "ເຮັດທ່າສັນຕິພາບ (ສອງນິ້ວ) ພາຍໃນວົງມົນ." },
  victory: { prompt: "ທ່າ V", instruction: "ເຮັດທ່າຕົວ V ພາຍໃນວົງມົນ." },
  open_palm: { prompt: "ແບມື", instruction: "ແບຝ່າມືອອກພາຍໃນວົງມົນ." },
  high_five: { prompt: "ໄຮໄຟວ໌", instruction: "ແບຝ່າມືແບບໄຮໄຟວ໌ພາຍໃນວົງມົນ." },
  stop: { prompt: "ທ່າຢຸດ", instruction: "ຍົກມືເຮັດທ່າຢຸດພາຍໃນວົງມົນ." },
  fist: { prompt: "ກຳມື", instruction: "ກຳມືພາຍໃນວົງມົນ." },
  thumb_up: { prompt: "ຍົກໂປ້ຂຶ້ນ", instruction: "ຍົກນິ້ວໂປ້ຂຶ້ນພາຍໃນວົງມົນ." },
  ok: { prompt: "ທ່າ OK", instruction: "ເຮັດທ່າ OK ພາຍໃນວົງມົນ." },
  pinch: { prompt: "ຈີບນິ້ວ", instruction: "ແຕະນິ້ວໂປ້ກັບນິ້ວຊີ້ພາຍໃນວົງມົນ." },
  small_ok: { prompt: "ທ່າ OK ນ້ອຍ", instruction: "ເຮັດທ່າ OK ນ້ອຍໆພາຍໃນວົງມົນ." },
  rock_on: { prompt: "ທ່າຣັອກ", instruction: "ຊູນິ້ວຊີ້ ແລະ ນິ້ວກ້ອຍພາຍໃນວົງມົນ." },
  call_me: { prompt: "ທ່າໂທຫາ", instruction: "ຊູນິ້ວໂປ້ ແລະ ນິ້ວກ້ອຍພາຍໃນວົງມົນ." },
  thumb_down: { prompt: "ຄວ່ຳໂປ້ລົງ", instruction: "ຄວ່ຳນິ້ວໂປ້ລົງພາຍໃນວົງມົນ." },
  i_love_you: { prompt: "ທ່າຮັກເຈົ້າ", instruction: "ເຮັດທ່າມື \"I love you\" ພາຍໃນວົງມົນ." },
  l_shape: { prompt: "ທ່າຕົວ L", instruction: "ໃຊ້ນິ້ວໂປ້ ແລະ ນິ້ວຊີ້ເຮັດເປັນຕົວ L ພາຍໃນວົງມົນ." },
  pinched_fingers: { prompt: "ຈີບປາຍນິ້ວ", instruction: "ເອົາປາຍນິ້ວທັງໝົດມາຕິດກັນ ຊີ້ຂຶ້ນເທິງພາຍໃນວົງມົນ." },
  crossed_fingers: { prompt: "ໄຂວ້ນິ້ວ", instruction: "ໄຂວ້ນິ້ວຊີ້ ແລະ ນິ້ວກາງພາຍໃນວົງມົນ." }
};

export function challengePrompt(challenge: ChallengeLike): string;
export function challengePrompt(challenge?: ChallengeLike): string | undefined;
export function challengePrompt(challenge?: ChallengeLike) {
  if (!challenge) return undefined;
  const lo = CHALLENGE_TEXT[challenge.id]?.prompt;
  return lo ? L(lo, challenge.prompt) : challenge.prompt;
}

export function challengeInstruction(challenge?: ChallengeLike) {
  if (!challenge) return undefined;
  const lo = CHALLENGE_TEXT[challenge.id]?.instruction;
  return lo ? L(lo, challenge.instruction) : challenge.instruction;
}

const STATUS_TEXT: Record<string, string> = {
  passed: "ຜ່ານ",
  pending: "ລໍຖ້າ",
  rejected: "ບໍ່ຜ່ານ",
  confirmed: "ຢືນຢັນແລ້ວ",
  dismissed: "ປັດຕົກ",
  failed: "ລົ້ມເຫຼວ",
  passport: "ໜັງສືຜ່ານແດນ",
  lao_id_card: "ບັດປະຈຳຕົວລາວ",
  admin: "ຜູ້ດູແລລະບົບ",
  operator: "ພະນັກງານ"
};

const STATUS_TEXT_EN: Record<string, string> = {
  passed: "Passed",
  pending: "Pending",
  rejected: "Rejected",
  confirmed: "Confirmed",
  dismissed: "Dismissed",
  failed: "Failed",
  passport: "Passport",
  lao_id_card: "Lao ID card",
  admin: "Admin",
  operator: "Operator"
};

/** Lao label for a decision / status / document-type value from the API. */
export function statusLabel(value: string | null | undefined) {
  if (!value) return "—";
  return L(STATUS_TEXT[value] ?? value, STATUS_TEXT_EN[value] ?? value);
}
