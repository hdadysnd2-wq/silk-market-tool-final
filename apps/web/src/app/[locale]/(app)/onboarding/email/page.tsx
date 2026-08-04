import { SendingEmailManager } from "@/components/SendingEmailManager";

// Onboarding step / alias of Settings › Sending email. Keeps the historical
// /onboarding/email path working (and shows the "continue to dashboard" link),
// while the canonical home for this UI is now /settings/sending-email.
export default function ConnectEmailPage() {
  return <SendingEmailManager showContinue />;
}
