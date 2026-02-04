import { NextResponse } from 'next/server';

export async function POST(req: Request) {
  try {
    const { email } = await req.json();

    // Mock taken emails
    const taken = ['test@example.com', 'taken@example.com'];
    const available = !taken.includes(String(email).toLowerCase());

    return NextResponse.json({ available });
  } catch (err) {
    return NextResponse.json({ error: 'Invalid request' }, { status: 400 });
  }
}
