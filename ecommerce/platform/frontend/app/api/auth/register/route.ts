import { NextResponse } from 'next/server';

export async function POST(req: Request) {
  try {
    const body = await req.json();
    const email = String(body.email || '').toLowerCase();

    // Mock taken emails
    const taken = ['test@example.com', 'taken@example.com'];
    if (taken.includes(email)) {
      return NextResponse.json({ error: 'Email already taken' }, { status: 400 });
    }

    // In a real app you'd create the user in DB here
    return NextResponse.json({ ok: true }, { status: 201 });
  } catch (err) {
    return NextResponse.json({ error: 'Invalid request' }, { status: 400 });
  }
}
