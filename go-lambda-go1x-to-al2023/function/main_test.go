package main

import (
	"context"
	"encoding/json"
	"io"
	"log/slog"
	"net/http"
	"testing"
	"time"

	"github.com/aws/aws-lambda-go/events"
)

func quietHandler() Handler {
	h := newHandler()
	h.logger = slog.New(slog.NewJSONHandler(io.Discard, nil))
	return h
}

func request(id string) events.APIGatewayV2HTTPRequest {
	return events.APIGatewayV2HTTPRequest{PathParameters: map[string]string{"id": id}}
}

func TestStatusCodes(t *testing.T) {
	cases := map[string]int{
		"ord-100001": http.StatusOK,
		"ord-999999": http.StatusNotFound,
		"100001":     http.StatusBadRequest,
		"":           http.StatusBadRequest,
	}
	for id, want := range cases {
		resp, err := quietHandler().Handle(context.Background(), request(id))
		if err != nil {
			t.Fatalf("%q: unexpected error %v", id, err)
		}
		if resp.StatusCode != want {
			t.Errorf("%q: status %d, want %d", id, resp.StatusCode, want)
		}
	}
}

func TestBodyOfKnownOrder(t *testing.T) {
	resp, _ := quietHandler().Handle(context.Background(), request("ord-100002"))
	var got Order
	if err := json.Unmarshal([]byte(resp.Body), &got); err != nil {
		t.Fatal(err)
	}
	if got.Status != "PICKING" || got.ID != "ord-100002" {
		t.Errorf("unexpected body %+v", got)
	}
}

func TestNearDeadlineAnswers503(t *testing.T) {
	ctx, cancel := context.WithTimeout(context.Background(), 50*time.Millisecond)
	defer cancel()
	resp, err := quietHandler().Handle(ctx, request("ord-100001"))
	if err != nil || resp.StatusCode != http.StatusServiceUnavailable {
		t.Fatalf("got %d, %v; want 503 and no error", resp.StatusCode, err)
	}
}

func TestCancelledContextIsAnError(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if _, err := quietHandler().Handle(ctx, request("ord-100001")); err == nil {
		t.Fatal("expected the store error to surface")
	}
}
